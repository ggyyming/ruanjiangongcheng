"""借用、延期、逾期、争议与通知的业务规则（CP-R-03/04/14-18/26/27）。"""

from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from .models import (
    BorrowAgreement,
    BorrowRestriction,
    Dispute,
    DisputeEvent,
    ExtensionRequest,
    Notification,
)
from .signals import (
    borrow_applications_should_close,
    borrow_ended,
    deposit_refund_requested,
)


class LoanError(Exception):
    """业务规则不满足；视图层转成可读提示，不改变任何状态。"""


def _now():
    return timezone.now()


def _fmt(moment):
    return timezone.localtime(moment).strftime("%Y-%m-%d %H:%M")


def notify(recipient, *, business_kind, business_ref, event, title, body=""):
    """写入一条站内通知；通知不替代交付、归还或资金结果确认（CP-D-20）。"""
    return Notification.objects.create(
        recipient=recipient,
        business_kind=business_kind,
        business_ref=str(business_ref),
        event=event,
        title=title,
        body=body,
    )


def _notify_pair(agreement, *, event, title, body=""):
    for user in (agreement.owner, agreement.borrower):
        notify(
            user,
            business_kind=Notification.Business.LOAN,
            business_ref=agreement.pk,
            event=event,
            title=title,
            body=body,
        )


def _require_party(agreement, actor):
    if not agreement.involves(actor):
        raise PermissionDenied("仅本次借用的当事双方可以操作。")


def _log(dispute, action, actor=None, note=""):
    return DisputeEvent.objects.create(dispute=dispute, action=action, actor=actor, note=note)


@transaction.atomic
def create_agreement(
    *,
    owner,
    borrower,
    item_ref,
    item_title,
    deposit_amount,
    application_ref="",
):
    """由流转包在物主选定借用申请人后调用；此时借用进入“待交付”。"""
    if owner.pk == borrower.pk:
        raise LoanError("物主与借用者不能是同一用户。")
    if not str(item_ref).strip() or not str(item_title).strip():
        raise LoanError("物品标识和名称不能为空。")
    try:
        amount = Decimal(str(deposit_amount))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise LoanError("押金金额格式不正确。") from exc
    if amount <= 0:
        raise LoanError("每次借用必须约定大于 0 的押金（CP-D-08）。")

    agreement = BorrowAgreement.objects.create(
        owner=owner,
        borrower=borrower,
        item_ref=str(item_ref),
        application_ref=str(application_ref or ""),
        item_title=item_title,
        deposit_amount=amount,
    )
    _notify_pair(
        agreement,
        event="loan.created",
        title="借用已建立，请约定归还时间",
        body="双方需在交付前分别确认同一归还日期和时间。",
    )
    return agreement


def set_due_date(agreement, actor, due_at):
    """任一方提出归还时间并自动确认己方；对方确认后约定才成立（CP-R-14、CP-ST-09）。"""
    _require_party(agreement, actor)
    if agreement.status != BorrowAgreement.Status.PENDING_DELIVERY:
        raise LoanError("只能在交付前约定归还时间。")
    if due_at <= _now():
        raise LoanError("归还时间必须晚于当前时间。")

    changed = agreement.due_at != due_at
    if changed:
        agreement.due_at = due_at
        agreement.due_owner_confirmed_at = None
        agreement.due_borrower_confirmed_at = None
    _set_due_side(agreement, actor)
    agreement.save()
    _after_due_change(agreement, actor, changed)
    return agreement


def confirm_due_date(agreement, actor):
    """确认现有利归还时间；重复确认保持既有结果（CP-ST-09）。"""
    _require_party(agreement, actor)
    if agreement.status != BorrowAgreement.Status.PENDING_DELIVERY:
        raise LoanError("只能在交付前确认归还时间。")
    if agreement.due_at is None:
        raise LoanError("尚未提出归还时间。")
    if _side_confirmed(agreement, actor):
        return agreement

    _set_due_side(agreement, actor)
    agreement.save()
    _after_due_change(agreement, actor, False)
    return agreement


def _set_due_side(agreement, actor):
    now = _now()
    if actor.pk == agreement.owner_id:
        agreement.due_owner_confirmed_at = now
    else:
        agreement.due_borrower_confirmed_at = now


def _side_confirmed(agreement, actor):
    if actor.pk == agreement.owner_id:
        return agreement.due_owner_confirmed_at is not None
    return agreement.due_borrower_confirmed_at is not None


def _after_due_change(agreement, actor, changed):
    if agreement.is_due_confirmed():
        _notify_pair(
            agreement,
            event="loan.due_date_confirmed",
            title="归还时间已由双方确认",
            body=f"约定归还时间：{_fmt(agreement.due_at)}（北京时间）。",
        )
        return
    other = agreement.borrower if actor.pk == agreement.owner_id else agreement.owner
    notify(
        other,
        business_kind=Notification.Business.LOAN,
        business_ref=agreement.pk,
        event="loan.due_date_pending",
        title="请确认归还时间",
        body=f"对方提出归还时间：{_fmt(agreement.due_at)}（北京时间）。",
    )


@transaction.atomic
def start_borrow(agreement):
    """由流转包在交付双确认且押金付清后调用；C 不校验资金记录。"""
    agreement = BorrowAgreement.objects.select_for_update().get(pk=agreement.pk)
    if agreement.status != BorrowAgreement.Status.PENDING_DELIVERY:
        raise LoanError("只有待交付的借用可以开始。")
    if not agreement.is_due_confirmed():
        raise LoanError("归还时间尚未由双方确认，不能开始借用。")
    if agreement.due_at <= _now():
        raise LoanError("约定的归还时间已过，不能开始借用。")

    agreement.status = BorrowAgreement.Status.ACTIVE
    agreement.started_at = _now()
    agreement.save()
    _notify_pair(
        agreement,
        event="loan.started",
        title="借用已开始",
        body=f"约定归还时间：{_fmt(agreement.due_at)}（北京时间）。",
    )
    return agreement


@transaction.atomic
def cancel_unstarted_agreement(agreement, reason):
    """交付前取消时由流转包调用，关闭借用记录（物品恢复规则由物品包处理）。"""
    agreement = BorrowAgreement.objects.select_for_update().get(pk=agreement.pk)
    if agreement.status != BorrowAgreement.Status.PENDING_DELIVERY:
        raise LoanError("只有待交付的借用可以取消。")
    agreement.status = BorrowAgreement.Status.CANCELLED
    agreement.cancel_reason = reason
    agreement.save()
    _notify_pair(
        agreement,
        event="loan.cancelled",
        title="借用已在交付前取消",
        body=reason,
    )
    borrow_ended.send(sender=BorrowAgreement, agreement=agreement, outcome="cancelled")
    return agreement


@transaction.atomic
def confirm_return(agreement, actor):
    """借用者确认交还、物主确认收回，双方确认后才记为已归还（CP-R-15）。"""
    _require_party(agreement, actor)
    agreement = BorrowAgreement.objects.select_for_update().get(pk=agreement.pk)

    dispute = agreement.open_dispute()
    if dispute:
        if dispute.kind == Dispute.Kind.LOSS:
            raise LoanError("物品已按丢失处理，不能确认归还。")
        raise LoanError("损坏争议尚未关闭，暂不能确认归还（CP-D-14）。")

    now = _now()
    if actor.pk == agreement.borrower_id:
        if agreement.handed_back_at is not None and agreement.status in (
            BorrowAgreement.Status.AWAITING_RETURN,
            BorrowAgreement.Status.RETURNED,
        ):
            return agreement
        if agreement.status != BorrowAgreement.Status.ACTIVE:
            raise LoanError("当前状态不能确认交还。")
        agreement.handed_back_at = now
        agreement.status = BorrowAgreement.Status.AWAITING_RETURN
        agreement.save()
        notify(
            agreement.owner,
            business_kind=Notification.Business.LOAN,
            business_ref=agreement.pk,
            event="loan.return_handed_back",
            title="借用者已确认交还，请确认收回",
            body="单方确认不会结束本次借用。",
        )
        return agreement

    if agreement.return_owner_confirmed_at is not None:
        return agreement
    if agreement.status != BorrowAgreement.Status.AWAITING_RETURN or not agreement.handed_back_at:
        raise LoanError("借用者尚未确认交还，物主暂不能确认收回。")

    agreement.return_owner_confirmed_at = now
    agreement.completed_at = now
    agreement.status = BorrowAgreement.Status.RETURNED
    agreement.save()
    _notify_pair(
        agreement,
        event="loan.returned",
        title="借用已归还",
        body="双方已确认归还；押金退款以资金模块记录为准。",
    )
    borrow_ended.send(sender=BorrowAgreement, agreement=agreement, outcome="returned")
    request_deposit_refund(agreement, "normal_return")
    release_restrictions_for(agreement.borrower)
    return agreement


@transaction.atomic
def request_extension(agreement, actor, proposed_due_at):
    """借用者在当前有效到期时刻前申请延期；待批不改变有效期限（CP-R-18、CP-D-19）。"""
    _require_party(agreement, actor)
    if actor.pk != agreement.borrower_id:
        raise LoanError("只有借用者可以申请延期。")
    agreement = BorrowAgreement.objects.select_for_update().get(pk=agreement.pk)
    if agreement.status != BorrowAgreement.Status.ACTIVE:
        raise LoanError("只有借用中的记录可以申请延期。")
    now = _now()
    if agreement.due_at is None or now >= agreement.due_at:
        raise LoanError("延期申请须在原到期时刻前提交。")
    if proposed_due_at <= agreement.due_at:
        raise LoanError("新的归还时间必须晚于当前约定。")
    if proposed_due_at <= now:
        raise LoanError("新的归还时间必须晚于当前时间。")
    if agreement.extensions.filter(status=ExtensionRequest.Status.PENDING).exists():
        raise LoanError("已有待审批的延期申请。")

    extension = ExtensionRequest.objects.create(
        agreement=agreement,
        previous_due_at=agreement.due_at,
        proposed_due_at=proposed_due_at,
        requested_by=actor,
    )
    notify(
        agreement.owner,
        business_kind=Notification.Business.LOAN,
        business_ref=agreement.pk,
        event="loan.extension_requested",
        title="借用者申请延期",
        body=f"申请延长至 {_fmt(proposed_due_at)}（北京时间），待你决定。",
    )
    return extension


@transaction.atomic
def decide_extension(extension, actor, approve):
    """物主决定延期；允许到期后批准，但新到期时刻须晚于批准时刻（CP-D-07）。"""
    extension = (
        ExtensionRequest.objects.select_for_update()
        .select_related("agreement")
        .get(pk=extension.pk)
    )
    agreement = extension.agreement
    if actor.pk != agreement.owner_id:
        raise PermissionDenied("只有物主可以审批延期。")
    if extension.status != ExtensionRequest.Status.PENDING:
        raise LoanError("该延期申请已处理。")

    now = _now()
    if approve and extension.proposed_due_at <= now:
        raise LoanError("批准时新到期时刻必须晚于当前时间。")

    extension.decided_at = now
    extension.decided_by = actor
    extension.status = (
        ExtensionRequest.Status.APPROVED if approve else ExtensionRequest.Status.REJECTED
    )
    extension.save()
    if approve:
        agreement.due_at = extension.proposed_due_at
        agreement.save()
        body = f"新归还时间：{_fmt(agreement.due_at)}（北京时间）。"
        if agreement.overdue_marked_at:
            body += "此前发生的逾期记录和新增借用限制不自动撤销。"
        notify(
            agreement.borrower,
            business_kind=Notification.Business.LOAN,
            business_ref=agreement.pk,
            event="loan.extension_approved",
            title="延期已被同意",
            body=body,
        )
    else:
        notify(
            agreement.borrower,
            business_kind=Notification.Business.LOAN,
            business_ref=agreement.pk,
            event="loan.extension_rejected",
            title="延期未获同意",
            body="仍按原约定归还时间处理。",
        )
    return extension


@transaction.atomic
def open_dispute(agreement, actor, kind, description, materials=""):
    """当事双方提交损坏/丢失争议；争议期间暂缓归还确认与自动退款（CP-R-26、CP-ST-29）。"""
    _require_party(agreement, actor)
    agreement = BorrowAgreement.objects.select_for_update().get(pk=agreement.pk)
    if agreement.has_open_dispute():
        raise LoanError("该借用已有未关闭争议。")
    if agreement.status not in (
        BorrowAgreement.Status.ACTIVE,
        BorrowAgreement.Status.AWAITING_RETURN,
    ):
        raise LoanError("只有借用中或待归还确认的记录可以提交争议。")
    if kind == Dispute.Kind.LOSS and agreement.status != BorrowAgreement.Status.ACTIVE:
        raise LoanError("丢失争议只能在借用中提交。")

    agreement.status_before_dispute = agreement.status
    agreement.status = BorrowAgreement.Status.DISPUTED
    agreement.save()
    dispute = Dispute.objects.create(
        agreement=agreement,
        kind=kind,
        opened_by=actor,
        description=description,
        materials=materials,
    )
    _log(dispute, "opened", actor, description)
    other = agreement.borrower if actor.pk == agreement.owner_id else agreement.owner
    notify(
        other,
        business_kind=Notification.Business.DISPUTE,
        business_ref=dispute.pk,
        event="dispute.opened",
        title="对方提交了借用争议",
        body="争议材料仅当事双方及负责处理的管理员可见。",
    )
    return dispute


@transaction.atomic
def record_plan(dispute, actor, plan):
    """记录协商方案；记录方案不等于已履行或争议已关闭（CP-D-12）。"""
    dispute = Dispute.objects.select_for_update().select_related("agreement").get(pk=dispute.pk)
    if dispute.status != Dispute.Status.OPEN:
        raise LoanError("争议已关闭，不能修改方案。")
    if not dispute.is_party(actor):
        raise PermissionDenied("仅本次争议的当事双方可以记录方案。")
    plan = (plan or "").strip()
    if not plan:
        raise LoanError("方案不能为空。")

    dispute.plan = plan
    dispute.plan_recorded_at = _now()
    dispute.plan_recorded_by = actor
    dispute.save()
    _log(dispute, "plan_recorded", actor, plan)
    other = (
        dispute.agreement.borrower
        if actor.pk == dispute.agreement.owner_id
        else dispute.agreement.owner
    )
    notify(
        other,
        business_kind=Notification.Business.DISPUTE,
        business_ref=dispute.pk,
        event="dispute.plan_recorded",
        title="争议方案已记录",
        body="记录方案不等于已履行；请双方分别确认履行并表达结束意见。",
    )
    return dispute


@transaction.atomic
def confirm_plan_performed(dispute, actor):
    """一方确认方案已履行；双方均确认且均同意结束后才由系统关闭（CP-D-12）。"""
    dispute = Dispute.objects.select_for_update().select_related("agreement").get(pk=dispute.pk)
    if dispute.status != Dispute.Status.OPEN:
        raise LoanError("争议已关闭。")
    if not dispute.is_party(actor):
        raise PermissionDenied("仅本次争议的当事双方可以确认履行。")
    if not dispute.plan:
        raise LoanError("请先记录赔偿或退款方案。")
    if actor.pk == dispute.agreement.owner_id:
        if dispute.owner_performed_at is not None:
            return dispute
        dispute.owner_performed_at = _now()
    else:
        if dispute.borrower_performed_at is not None:
            return dispute
        dispute.borrower_performed_at = _now()
    dispute.save()
    _log(dispute, "performed_confirmed", actor)
    _maybe_auto_close(dispute)
    return dispute


@transaction.atomic
def agree_dispute_end(dispute, actor):
    """一方同意结束；双方都同意且均已确认履行后系统关闭，否则转管理员（CP-D-12）。"""
    dispute = Dispute.objects.select_for_update().select_related("agreement").get(pk=dispute.pk)
    if dispute.status != Dispute.Status.OPEN:
        raise LoanError("争议已关闭。")
    if not dispute.is_party(actor):
        raise PermissionDenied("仅本次争议的当事双方可以表达结束意见。")
    if not dispute.plan:
        raise LoanError("请先记录赔偿或退款方案。")
    if actor.pk == dispute.agreement.owner_id:
        if dispute.owner_end_agreed_at is not None:
            return dispute
        dispute.owner_end_agreed_at = _now()
    else:
        if dispute.borrower_end_agreed_at is not None:
            return dispute
        dispute.borrower_end_agreed_at = _now()
    dispute.save()
    _log(dispute, "end_agreed", actor)
    _maybe_auto_close(dispute)
    return dispute


def _maybe_auto_close(dispute):
    dispute.refresh_from_db()
    if dispute.both_performed() and dispute.both_end_agreed():
        _close_dispute(dispute, closed_by=None)


@transaction.atomic
def claim_dispute(dispute, admin):
    """管理员认领争议；认领后仅该管理员可查看和处理材料（CP-D-22）。"""
    if not getattr(admin, "is_staff", False):
        raise PermissionDenied("仅管理员可以认领争议。")
    dispute = Dispute.objects.select_for_update().get(pk=dispute.pk)
    if dispute.assigned_admin_id is not None and dispute.assigned_admin_id != admin.pk:
        raise PermissionDenied("该争议已由其他管理员负责。")
    if dispute.assigned_admin_id is None:
        dispute.assigned_admin = admin
        dispute.save()
        _log(dispute, "admin_claimed", admin)
    return dispute


@transaction.atomic
def admin_close_dispute(dispute, admin, resolution=""):
    """双方意见不一致时由负责管理员关闭；履行确认仍须双方分别完成（CP-D-12）。"""
    if not getattr(admin, "is_staff", False):
        raise PermissionDenied("仅管理员可以处理争议。")
    dispute = Dispute.objects.select_for_update().select_related("agreement").get(pk=dispute.pk)
    if dispute.assigned_admin_id is not None and dispute.assigned_admin_id != admin.pk:
        raise PermissionDenied("该争议已由其他管理员负责。")
    if dispute.status != Dispute.Status.OPEN:
        raise LoanError("争议已关闭。")
    if not dispute.both_performed():
        raise LoanError("双方尚未分别确认方案已履行，管理员不能关闭争议。")

    dispute.assigned_admin = dispute.assigned_admin or admin
    dispute.resolution = (resolution or "").strip()
    dispute.save()
    _log(dispute, "admin_closed", admin, dispute.resolution)
    _close_dispute(dispute, closed_by=admin)
    return dispute


def _close_dispute(dispute, *, closed_by):
    now = _now()
    dispute.status = Dispute.Status.CLOSED
    dispute.closed_at = now
    dispute.closed_by = closed_by
    dispute.save()

    agreement = dispute.agreement
    if dispute.kind == Dispute.Kind.LOSS:
        agreement.status = BorrowAgreement.Status.COMPENSATED
        agreement.compensated_at = now
        agreement.status_before_dispute = ""
        agreement.save()
        borrow_ended.send(sender=BorrowAgreement, agreement=agreement, outcome="compensated")
        request_deposit_refund(agreement, "loss_compensated")
    else:
        restore = agreement.status_before_dispute or BorrowAgreement.Status.ACTIVE
        if restore == BorrowAgreement.Status.DISPUTED:
            restore = BorrowAgreement.Status.ACTIVE
        agreement.status = restore
        agreement.status_before_dispute = ""
        agreement.save()

    _log(dispute, "closed", closed_by, dispute.resolution)
    _notify_pair(
        agreement,
        event="dispute.closed",
        title="借用争议已关闭",
        body="争议关闭不改变押金到账状态，资金结果以资金记录为准。",
    )
    release_restrictions_for(agreement.borrower)


def _ensure_restriction(user, reason):
    restriction, created = BorrowRestriction.objects.get_or_create(
        user=user,
        cause=BorrowRestriction.CAUSE_OVERDUE,
        active=True,
        defaults={"reason": reason},
    )
    if created:
        notify(
            user,
            business_kind=Notification.Business.LOAN,
            business_ref=user.pk,
            event="loan.restriction_applied",
            title="新增借用已受限",
            body="存在逾期未有效结束的借用；已有借用的归还不受影响。",
        )
    return restriction


def is_borrow_restricted(user):
    """供流转包在创建借用申请前检查（CP-R-09、CP-BR-13）。"""
    return BorrowRestriction.objects.filter(
        user=user, cause=BorrowRestriction.CAUSE_OVERDUE, active=True
    ).exists()


def release_restrictions_for(user):
    """全部逾期借用已归还或赔偿结清且相关争议关闭后，自动解除本项限制（CP-BR-14）。"""
    active = BorrowRestriction.objects.filter(
        user=user, cause=BorrowRestriction.CAUSE_OVERDUE, active=True
    )
    if not active.exists():
        return False
    overdue = BorrowAgreement.objects.filter(borrower=user, overdue_marked_at__isnull=False)
    if overdue.exclude(
        status__in=(BorrowAgreement.Status.RETURNED, BorrowAgreement.Status.COMPENSATED)
    ).exists():
        return False
    if Dispute.objects.filter(agreement__in=overdue, status=Dispute.Status.OPEN).exists():
        return False

    active.update(active=False, released_at=_now())
    notify(
        user,
        business_kind=Notification.Business.LOAN,
        business_ref=user.pk,
        event="loan.restriction_released",
        title="新增借用限制已解除",
        body="全部逾期借用已有效结束且相关争议已关闭；本项限制解除不影响其他限制。",
    )
    return True


@transaction.atomic
def scan_overdue(now=None):
    """扫描逾期借用：标记、提醒双方、限制借用者并通知流转包关闭未选定申请（CP-ST-31）。"""
    now = now or _now()
    agreements = BorrowAgreement.objects.filter(
        status__in=(BorrowAgreement.Status.ACTIVE, BorrowAgreement.Status.AWAITING_RETURN),
        due_at__lt=now,
        overdue_marked_at__isnull=True,
    ).select_related("owner", "borrower")

    marked = 0
    for agreement in agreements:
        agreement.overdue_marked_at = now
        agreement.save(update_fields=("overdue_marked_at", "updated_at"))
        _notify_pair(
            agreement,
            event="loan.overdue",
            title="借用已逾期",
            body=f"约定归还时间 {_fmt(agreement.due_at)} 已过，请尽快处理归还。",
        )
        _ensure_restriction(agreement.borrower, "存在逾期未有效结束的借用")
        borrow_applications_should_close.send(
            sender=BorrowRestriction,
            user=agreement.borrower,
            reason="借用已逾期，关闭未被选定的借用申请",
        )
        marked += 1
    return marked


def request_deposit_refund(agreement, reason):
    """向资金包请求全额原路退款；同一借用只发起一次，到账状态由资金包记录。"""
    if agreement.deposit_refund_requested_at is not None:
        return False
    agreement.deposit_refund_requested_at = _now()
    agreement.deposit_refund_reason = reason
    agreement.save(
        update_fields=("deposit_refund_requested_at", "deposit_refund_reason", "updated_at")
    )
    _notify_pair(
        agreement,
        event="funds.deposit_refund_requested",
        title="已提交押金退款申请",
        body="退款由资金模块处理，发起不等于到账；以资金记录为准。",
    )
    deposit_refund_requested.send(sender=BorrowAgreement, agreement=agreement, reason=reason)
    return True
