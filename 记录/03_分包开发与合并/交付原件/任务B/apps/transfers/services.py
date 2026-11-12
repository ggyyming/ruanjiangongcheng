"""流转服务：申请、预留、交付确认、交付前取消。

本包所有业务状态变更必须经本模块函数执行，视图不得直接修改模型状态（共同约定 §3）。
A（accounts/catalog）与 C（loans/disputes/notifications）的依赖在函数体内按需导入，
避免模块顶层相互导入导致启动失败（共同约定 §2「模型关系使用字符串外键」同理）。

对 A 的 Item 字段访问集中在 ``_item_kind`` / ``_fixed_amount``，字段名以 A0 实际为准：
假定 Item 拥有 ``owner``（物主）、``kind``（流转类型 sale/donation/borrow）、
``price``（售价）、``deposit``（借用押金展示）。集成时如需调整只改这两个函数。

违反业务规则抛 Django 的 PermissionDenied / ValidationError，视图转换为明确拒绝；
所有写操作包在事务内，拒绝不得留下半笔数据。
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Application, Revocation, Transfer, TransferLog

# 付款用途取值，与 payments.PaymentOperation.Purpose 保持一致
PURPOSE_SALE = "sale"
PURPOSE_DEPOSIT = "deposit"


def _item_kind(item):
    """读取 A 的物品流转类型。假定字段名为 ``kind``，取值 sale/donation/borrow。"""
    return item.kind


def _fixed_amount(item, kind):
    """预留时固化的金额：买卖为售价、借用为押金展示、赠送为空。

    借用最终押金按 C 的双方约定固化（共同约定 §2），初始以物品押金展示为准，
    ``payments.services.request_payment`` 可用 ``amount`` 参数覆盖为约定金额。
    """
    if kind == Transfer.Kind.SALE:
        return item.price
    if kind == Transfer.Kind.BORROW:
        return item.deposit
    return None


def _purpose_for(transfer):
    """流转对应的付款用途；赠送无资金，返回 None。"""
    if transfer.kind == Transfer.Kind.SALE:
        return PURPOSE_SALE
    if transfer.kind == Transfer.Kind.BORROW:
        return PURPOSE_DEPOSIT
    return None


def _log(transfer, actor, action, from_status, to_status, note=""):
    TransferLog.objects.create(
        transfer=transfer,
        actor=actor,
        action=action,
        from_status=from_status,
        to_status=to_status,
        note=note,
    )


def apply(*, actor, item_id):
    """提交流转申请（CP-ST-03、CP-R-07/09）。

    校验：校内认证、非本人物品、物品可申请、借用另查借用限制。
    """
    from apps.catalog.models import Item  # noqa: F401 - A 的模型

    item = Item.objects.select_related("owner").get(pk=item_id)

    from apps.accounts.services import is_verified  # A

    if not is_verified(user_id=actor.id):
        raise PermissionDenied("未通过校内身份审核，不能申请流转")
    if item.owner_id == actor.id:
        raise ValidationError("不能申请自己发布的物品")

    kind = _item_kind(item)

    # 借用另查借用限制（CP-ST-03「借用另检查限制」）
    if kind == Transfer.Kind.BORROW:
        from apps.loans.services import can_borrow  # C

        if not can_borrow(user_id=actor.id):
            raise PermissionDenied("存在未结束的逾期借用，暂不能新增借用")

    # 物品可申请：A 的展示资格 + 本包无进行中流转
    from apps.catalog.services import can_display  # A

    if not can_display(item_id=item.id):
        raise ValidationError("物品当前不可申请")
    if Transfer.objects.filter(
        item=item, status__in=[Transfer.Status.RESERVED, Transfer.Status.BORROWED]
    ).exists():
        raise ValidationError("物品已被预留或借出，不能申请")

    try:
        application = Application.objects.create(item=item, applicant=actor, kind=kind)
    except IntegrityError:
        raise ValidationError("已提交过该物品的申请，请勿重复申请") from None
    return application


@transaction.atomic
def reserve(*, actor, application_id):
    """物主选择一名申请人并预留（CP-ST-04、CP-R-09、CP-BR-06）。

    原子关闭同物品其他待选择申请；唯一约束兜底并发下的唯一预留。
    """
    application = (
        Application.objects.select_related("item__owner").select_for_update().get(pk=application_id)
    )
    if application.status != Application.Status.PENDING:
        raise ValidationError("该申请已处理，请刷新后重试")
    if application.item.owner_id != actor.id:
        raise PermissionDenied("只有物主可以选择申请人")

    # 借用再次检查资格（CP-ST-04）
    if application.kind == Application.Kind.BORROW:
        from apps.loans.services import can_borrow  # C

        if not can_borrow(user_id=application.applicant_id):
            raise ValidationError("申请人存在借用限制，不能借用")

    # 条件更新：只有仍是待选择才推进，防并发重复选择
    updated = Application.objects.filter(
        pk=application.pk, status=Application.Status.PENDING
    ).update(status=Application.Status.SELECTED)
    if not updated:
        raise ValidationError("该申请已被处理，请刷新后重试")

    # 原子关闭同物品其他待选择申请（CP-BR-06「其他申请关闭」）
    Application.objects.filter(
        item_id=application.item_id, status=Application.Status.PENDING
    ).update(status=Application.Status.CLOSED, close_reason="物主选择了其他申请人")

    amount = _fixed_amount(application.item, application.kind)
    try:
        transfer = Transfer.objects.create(
            application=application,
            item=application.item,
            owner=application.item.owner,
            recipient=application.applicant,
            kind=application.kind,
            amount=amount,
            status=Transfer.Status.RESERVED,
        )
    except IntegrityError:
        # 唯一约束：该物品已有进行中流转
        raise ValidationError("物品已被预留，不能重复选择") from None

    # 通知 A：物品已预留（不可再申请）
    from apps.catalog.services import change_availability  # A

    change_availability(item_id=application.item_id, available=False, reason="已预留")

    _log(transfer, actor, "reserve", "", Transfer.Status.RESERVED, "选择申请人并预留")
    return transfer


@transaction.atomic
def confirm_delivery(*, actor, transfer_id):
    """一方确认交付（CP-ST-05/06/10、CP-BR-07、CP-R-10）。

    单方确认不完成；双方都确认后才完成对应流转。重复确认幂等，不替对方确认。
    买卖须货款付清、借用须 C 的期限/押金约定就绪且押金付清；撤销协商中暂停。
    """
    transfer = Transfer.objects.select_related("item").select_for_update().get(pk=transfer_id)
    if transfer.status != Transfer.Status.RESERVED:
        raise ValidationError("当前状态不能确认交付")
    if transfer.revoke_status == Transfer.RevokeStatus.NEGOTIATING:
        raise ValidationError("撤销协商中，暂停交付确认（CP-D-13）")

    if actor.id == transfer.owner_id:
        side = "owner"
    elif actor.id == transfer.recipient_id:
        side = "recipient"
    else:
        raise PermissionDenied("只有本次流转当事人可以确认交付")

    # 资金/期限前提
    if transfer.kind == Transfer.Kind.SALE:
        from apps.payments.services import is_paid

        if not is_paid(transfer_id=transfer.id, purpose=PURPOSE_SALE):
            raise ValidationError("买家尚未付款成功，不能确认交付（CP-BR-20）")
    elif transfer.kind == Transfer.Kind.BORROW:
        from apps.loans.services import delivery_ready  # C
        from apps.payments.services import is_paid

        if not delivery_ready(transfer_id=transfer.id):
            raise ValidationError("归还日期与押金金额尚未双方确认，不能借出")
        if not is_paid(transfer_id=transfer.id, purpose=PURPOSE_DEPOSIT):
            raise ValidationError("押金尚未付清，不能借出（CP-BR-19）")

    # 幂等：本人重复确认不重复记录（CP-BR-07）
    if side == "owner":
        if transfer.owner_confirmed_at is not None:
            return transfer
        transfer.owner_confirmed_at = timezone.now()
    else:
        if transfer.recipient_confirmed_at is not None:
            return transfer
        transfer.recipient_confirmed_at = timezone.now()

    both = transfer.both_confirmed
    from_status = transfer.status
    to_status = transfer.status
    if both:
        transfer.completed_at = timezone.now()
        if transfer.kind == Transfer.Kind.SALE:
            to_status = Transfer.Status.COMPLETED
        elif transfer.kind == Transfer.Kind.DONATION:
            to_status = Transfer.Status.DONATION_COMPLETED
        elif transfer.kind == Transfer.Kind.BORROW:
            to_status = Transfer.Status.BORROWED
        transfer.status = to_status

    transfer.save(
        update_fields=[
            "owner_confirmed_at",
            "recipient_confirmed_at",
            "status",
            "completed_at",
        ]
    )
    _log(transfer, actor, "confirm_delivery", from_status, to_status, f"{side} 确认交付")

    if both:
        if transfer.kind == Transfer.Kind.SALE:
            # 双方确认交付后发起向卖家结算（CP-ST-06、CP-R-24）
            from apps.payments.services import initiate_settlement

            initiate_settlement(transfer_id=transfer.id)
        elif transfer.kind == Transfer.Kind.BORROW:
            # 借出双确认后启动借用（CP-ST-10）
            from apps.loans.services import start_loan  # C

            start_loan(transfer_id=transfer.id)
    return transfer


def _refund_if_paid(transfer, reason):
    """已付款且无未解决争议时，全额原路退款（CP-BR-22/23、CP-ST-17）。"""
    purpose = _purpose_for(transfer)
    if purpose is None:
        return
    from apps.payments.services import is_paid, request_refund

    if not is_paid(transfer_id=transfer.id, purpose=purpose):
        return
    from apps.disputes.services import has_open_dispute  # C

    if has_open_dispute(transfer_id=transfer.id):
        return
    request_refund(transfer_id=transfer.id, reason=reason)


def _finalize_cancellation(transfer, reason):
    """把一笔已预留流转置为已取消，并让 A 按展示资格处理物品。"""
    transfer.status = Transfer.Status.CANCELLED
    transfer.cancelled_at = timezone.now()
    transfer.save(update_fields=["status", "cancelled_at"])

    Application.objects.filter(pk=transfer.application_id).update(
        status=Application.Status.CANCELLED, close_reason=reason
    )

    from apps.catalog.services import change_availability  # A

    # 物品仍符合展示条件则恢复可申请，否则保持下架（CP-BR-08，由 A 校验）
    change_availability(item_id=transfer.item_id, available=True, reason=reason)


@transaction.atomic
def cancel_before_delivery(*, actor, transfer_id, reason):
    """交付前取消（CP-ST-13/14、CP-BR-08、CP-R-11）。

    双方均未确认交付时任一方可取消并记录原因；已有一方确认改用协商撤销。
    已付款且无争议时按条件退款。
    """
    transfer = Transfer.objects.select_for_update().get(pk=transfer_id)
    if transfer.status != Transfer.Status.RESERVED:
        raise ValidationError("当前状态不能取消")
    if actor.id not in (transfer.owner_id, transfer.recipient_id):
        raise PermissionDenied("只有本次流转当事人可以取消")
    if transfer.owner_confirmed_at is not None or transfer.recipient_confirmed_at is not None:
        raise ValidationError("已有一方确认交付，不能单方取消，请走协商撤销（CP-BR-09）")
    if not reason:
        raise ValidationError("取消必须记录原因（CP-BR-08）")

    _finalize_cancellation(transfer, reason)
    _log(
        transfer,
        actor,
        "cancel_before_delivery",
        Transfer.Status.RESERVED,
        Transfer.Status.CANCELLED,
        reason,
    )

    # 已付款且无未解决争议 -> 全额原路退款（CP-BR-22）
    _refund_if_paid(transfer, f"交付前取消：{reason}")
    return transfer


def _party_side(transfer, actor):
    """判断 actor 是物主还是获选接收方；非当事人抛 PermissionDenied。"""
    if actor.id == transfer.owner_id:
        return Revocation.Side.OWNER
    if actor.id == transfer.recipient_id:
        return Revocation.Side.RECIPIENT
    raise PermissionDenied("只有本次流转当事人可以操作")


def _maybe_complete_revoke(transfer, revocation):
    """双方一致（都同意）且去向双确认（都声明且一致）后撤销生效（CP-ST-17）。"""
    if revocation.owner_direction is None or revocation.recipient_direction is None:
        return
    if revocation.owner_agreed_at is None or revocation.recipient_agreed_at is None:
        return
    if revocation.owner_direction != revocation.recipient_direction:
        # 双方声明不一致：撤销不能自动生效，需管理员介入（CP-BR-10）
        _log(
            transfer,
            None,
            "revoke_conflict",
            transfer.status,
            transfer.status,
            "双方去向声明不一致，转管理员",
        )
        return

    transfer.status = Transfer.Status.REVOKED
    transfer.revoke_status = Transfer.RevokeStatus.REVOKED
    transfer.save(update_fields=["status", "revoke_status"])

    # 撤销生效后物品下架（CP-ST-17），重新开放按 CP-D-11 由物主申请
    from apps.catalog.services import change_availability  # A

    change_availability(item_id=transfer.item_id, available=False, reason="协商撤销生效，物品下架")

    _log(
        transfer,
        None,
        "revoke_completed",
        Transfer.Status.RESERVED,
        Transfer.Status.REVOKED,
        "双方一致且去向双确认，撤销生效",
    )
    _refund_if_paid(transfer, "协商撤销生效：双方同意并核实去向")


@transaction.atomic
def start_revoke(*, actor, transfer_id, reason):
    """发起协商撤销（CP-BR-09、CP-ST-16）。

    仅限交付后有一方已确认、尚未完成时；发起方视为同意撤销。
    """
    transfer = Transfer.objects.select_for_update().get(pk=transfer_id)
    if transfer.status != Transfer.Status.RESERVED:
        raise ValidationError("当前状态不能发起撤销协商")
    side = _party_side(transfer, actor)
    if transfer.owner_confirmed_at is None and transfer.recipient_confirmed_at is None:
        raise ValidationError("双方均未确认交付，请直接取消（CP-BR-08）")
    if transfer.revoke_status != Transfer.RevokeStatus.NONE:
        raise ValidationError("已在撤销协商中，请勿重复发起")
    if not reason:
        raise ValidationError("发起撤销协商必须记录原因")

    revocation = Revocation.objects.create(
        transfer=transfer,
        initiator=side,
        reason=reason,
        owner_agreed_at=timezone.now() if side == Revocation.Side.OWNER else None,
        recipient_agreed_at=timezone.now() if side == Revocation.Side.RECIPIENT else None,
    )
    transfer.revoke_status = Transfer.RevokeStatus.NEGOTIATING
    transfer.save(update_fields=["revoke_status"])
    _log(transfer, actor, "start_revoke", transfer.status, transfer.status, reason)
    return revocation


@transaction.atomic
def declare_direction(*, actor, transfer_id, direction):
    """声明物品去向：未交出或已退回（CP-BR-10、CP-ST-16）。重复声明幂等。"""
    if direction not in Revocation.Direction.values:
        raise ValidationError("无效的物品去向声明")
    transfer = Transfer.objects.select_for_update().get(pk=transfer_id)
    if transfer.revoke_status != Transfer.RevokeStatus.NEGOTIATING:
        raise ValidationError("当前不在撤销协商中")
    side = _party_side(transfer, actor)
    revocation = Revocation.objects.select_for_update().get(transfer=transfer)

    field = f"{side}_direction"
    if getattr(revocation, field) is not None:
        return revocation
    setattr(revocation, field, direction)
    setattr(revocation, f"{side}_direction_at", timezone.now())
    revocation.save(update_fields=[field, f"{side}_direction_at"])
    _log(
        transfer,
        actor,
        "declare_direction",
        transfer.status,
        transfer.status,
        f"{side} 声明 {Revocation.Direction(direction).label}",
    )
    _maybe_complete_revoke(transfer, revocation)
    return revocation


@transaction.atomic
def agree_revoke(*, actor, transfer_id):
    """同意撤销（CP-ST-17「另一方确认并同意撤销」）。发起方已同意，重复同意幂等。"""
    transfer = Transfer.objects.select_for_update().get(pk=transfer_id)
    if transfer.revoke_status != Transfer.RevokeStatus.NEGOTIATING:
        raise ValidationError("当前不在撤销协商中")
    side = _party_side(transfer, actor)
    revocation = Revocation.objects.select_for_update().get(transfer=transfer)

    field = f"{side}_agreed_at"
    if getattr(revocation, field) is not None:
        return revocation
    setattr(revocation, field, timezone.now())
    revocation.save(update_fields=[field])
    _log(transfer, actor, "agree_revoke", transfer.status, transfer.status, f"{side} 同意撤销")
    _maybe_complete_revoke(transfer, revocation)
    return revocation


@transaction.atomic
def withdraw_revoke(*, actor, transfer_id):
    """撤回撤销申请（CP-ST-34）。双方都撤回后恢复原流程与既有确认，不清除历史。"""
    transfer = Transfer.objects.select_for_update().get(pk=transfer_id)
    if transfer.revoke_status != Transfer.RevokeStatus.NEGOTIATING:
        raise ValidationError("当前不在撤销协商中")
    side = _party_side(transfer, actor)
    revocation = Revocation.objects.select_for_update().get(transfer=transfer)

    field = f"{side}_withdrawn_at"
    if getattr(revocation, field) is not None:
        return revocation
    setattr(revocation, field, timezone.now())
    revocation.save(update_fields=[field])
    _log(
        transfer, actor, "withdraw_revoke", transfer.status, transfer.status, f"{side} 撤回撤销申请"
    )

    if revocation.owner_withdrawn_at is not None and revocation.recipient_withdrawn_at is not None:
        transfer.revoke_status = Transfer.RevokeStatus.NONE
        transfer.save(update_fields=["revoke_status"])
        _log(
            transfer,
            None,
            "revoke_withdrawn",
            transfer.status,
            transfer.status,
            "双方撤回撤销申请，恢复原流程",
        )
    return revocation


def cancel_reservation_for_timeout(transfer):
    """24 小时付款超时取消（CP-ST-37、CP-D-17）。仅系统命令调用，确认未付款后才取消。"""
    _finalize_cancellation(transfer, "预留满24小时仍未付款，取消预留")
    _log(
        transfer,
        None,
        "payment_timeout",
        Transfer.Status.RESERVED,
        Transfer.Status.CANCELLED,
        "24小时付款超时",
    )
    return transfer


def active_transfer_for_item(*, item_id):
    """A 查询物品当前进行中的流转（已预留或已借出），用于禁止编辑、展示资格等。

    返回 Transfer 或 None。签名待 M0 与 A 复核确认。
    """
    return (
        Transfer.objects.filter(
            item_id=item_id,
            status__in=[Transfer.Status.RESERVED, Transfer.Status.BORROWED],
        )
        .select_related("owner", "recipient")
        .first()
    )


def close_pending_loan_applications(*, user_id, reason):
    """关闭用户尚未被选定的借用申请（CP-D-21，由 C 的逾期限制触发）。

    只关闭借用且待选择的申请，不动买卖/受赠及已预留。
    """
    return Application.objects.filter(
        applicant_id=user_id,
        kind=Application.Kind.BORROW,
        status=Application.Status.PENDING,
    ).update(status=Application.Status.CLOSED, close_reason=reason)
