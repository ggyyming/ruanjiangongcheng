"""模拟资金服务：支付、结算、退款与模拟回执。

资金全部模拟（CP-R-19/20）。核心约束：

- 发起、处理中、到账（成功）分开记录，发起不等于到账（CP-ST-20~24）。
- 「处理中 -> 到账/失败/未知」只能由受控模拟回执 ``apply_simulated_receipt`` 驱动，
  普通用户不能直接写成功（共同约定 §4）。
- 退款/结算失败先对账，最多自动重试 3 次（不含首次），仍失败转人工；未知先查明，不盲重试
  （CP-D-09/18）；同一业务标识防重复处理。
- 金额统一 Decimal，禁止浮点（共同约定 §4）。
"""

from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import PaymentOperation

# 用途，与 transfers.services 中 PURPOSE_SALE / PURPOSE_DEPOSIT 一致
PURPOSE_SALE = "sale"
PURPOSE_DEPOSIT = "deposit"

# 结算/退款自动重试上限（不含首次）
MAX_AUTO_RETRIES = 3

# 回执结果取值
RECEIPT_SUCCESS = "success"
RECEIPT_FAILURE = "failure"
RECEIPT_UNKNOWN = "unknown"

# 各 kind 的「处理中 -> 成功/失败」状态映射
_PROCESSING_BY_KIND = {
    PaymentOperation.Kind.PAYMENT: PaymentOperation.Status.PAYING,
    PaymentOperation.Kind.SETTLEMENT: PaymentOperation.Status.SETTLING,
    PaymentOperation.Kind.REFUND: PaymentOperation.Status.REFUNDING,
}
_SUCCESS_BY_KIND = {
    PaymentOperation.Kind.PAYMENT: PaymentOperation.Status.PAID,
    PaymentOperation.Kind.SETTLEMENT: PaymentOperation.Status.SETTLED,
    PaymentOperation.Kind.REFUND: PaymentOperation.Status.REFUNDED,
}
_FAILURE_BY_KIND = {
    PaymentOperation.Kind.PAYMENT: PaymentOperation.Status.PAY_FAILED,
    PaymentOperation.Kind.SETTLEMENT: PaymentOperation.Status.SETTLE_FAILED,
    PaymentOperation.Kind.REFUND: PaymentOperation.Status.REFUND_FAILED,
}


def _business_id(transfer_id, kind, purpose):
    return f"{transfer_id}:{kind}:{purpose}"


def payment_deadline(transfer):
    return transfer.reserved_at + timedelta(hours=24)


def is_paid(*, transfer_id, purpose):
    """依据持久化的成功结果判断是否已支付（共同约定 §3），不信任浏览器声明。"""
    return PaymentOperation.objects.filter(
        transfer_id=transfer_id,
        kind=PaymentOperation.Kind.PAYMENT,
        purpose=purpose,
        status=PaymentOperation.Status.PAID,
    ).exists()


@transaction.atomic
def request_payment(*, transfer_id, purpose):
    """发起货款/押金支付（CP-ST-20、CP-BR-17/20）。

    借用押金以双方约定为准。失败可重试，未知先对账。
    """
    from apps.transfers.models import Transfer

    transfer = Transfer.objects.select_for_update().get(pk=transfer_id)
    if transfer.status != Transfer.Status.RESERVED:
        raise ValidationError("当前状态不能发起支付")
    if transfer.revoke_status != Transfer.RevokeStatus.NONE:
        raise ValidationError("撤销协商中，暂停付款")
    if timezone.now() >= payment_deadline(transfer):
        raise ValidationError("已超过预留付款期限，请查看付款结果")

    if purpose == PURPOSE_SALE:
        if transfer.kind != Transfer.Kind.SALE:
            raise ValidationError("只有买卖需要货款")
        target = transfer.amount
    elif purpose == PURPOSE_DEPOSIT:
        from apps.loans.services import delivery_ready

        if transfer.kind != Transfer.Kind.BORROW:
            raise ValidationError("只有借用需要押金")
        if not delivery_ready(transfer_id=transfer.id):
            raise ValidationError("请先由双方确认归还时间和押金金额")
        target = transfer.borrow_agreement.deposit_amount
        if transfer.amount != target:
            transfer.amount = target
            transfer.save(update_fields=["amount"])
    else:
        raise ValidationError("无效付款用途")

    if target is None or target <= 0:
        raise ValidationError("金额无效")

    business_id = _business_id(transfer.id, PaymentOperation.Kind.PAYMENT, purpose)
    op, created = PaymentOperation.objects.get_or_create(
        business_id=business_id,
        defaults=dict(
            transfer=transfer,
            kind=PaymentOperation.Kind.PAYMENT,
            purpose=purpose,
            amount=target,
            status=PaymentOperation.Status.PAYING,
        ),
    )
    if not created:
        if op.status == PaymentOperation.Status.PAY_FAILED:
            # 用户核对后重新发起（CP-ST-20），支付不计入 3 次自动重试
            op.status = PaymentOperation.Status.PAYING
            op.save(update_fields=["status", "updated_at"])
        elif op.status == PaymentOperation.Status.UNKNOWN:
            raise ValidationError("付款结果还未确认，请等待结果，避免重复付款。")
        # 已支付 / 处理中 幂等返回
    return op


@transaction.atomic
def pay_transfer(*, actor, transfer_id):
    """获选接收方发起（模拟）付款，按流转类型确定用途（CP-R-19）。

    买卖付货款、借用付押金、赠送无付款。撤销协商中暂停付款。
    """
    from apps.transfers.models import Transfer

    transfer = Transfer.objects.select_for_update().get(pk=transfer_id)
    if actor.id != transfer.recipient_id:
        raise PermissionDenied("只有获选接收方可以发起付款")
    if transfer.status != Transfer.Status.RESERVED:
        raise ValidationError("当前状态不能付款")
    if transfer.revoke_status == Transfer.RevokeStatus.NEGOTIATING:
        raise ValidationError("撤销协商期间暂不能付款。")

    if transfer.kind == Transfer.Kind.SALE:
        purpose = PURPOSE_SALE
    elif transfer.kind == Transfer.Kind.BORROW:
        purpose = PURPOSE_DEPOSIT
    else:
        raise ValidationError("赠送流转无需付款")
    return request_payment(transfer_id=transfer.id, purpose=purpose)


@transaction.atomic
def initiate_settlement(*, transfer_id):
    """买卖双方确认交付后发起向卖家结算（CP-ST-06、CP-BR-21、CP-R-24）。"""
    from apps.transfers.models import Transfer

    transfer = Transfer.objects.select_for_update().get(pk=transfer_id)
    if transfer.kind != Transfer.Kind.SALE:
        raise ValidationError("只有买卖需要结算")
    if transfer.status != Transfer.Status.COMPLETED:
        raise ValidationError("双方确认交付后才能发起结算")
    if transfer.revoke_status == Transfer.RevokeStatus.NEGOTIATING:
        raise ValidationError("撤销协商期间暂不能结算。")
    if not is_paid(transfer_id=transfer_id, purpose=PURPOSE_SALE):
        raise ValidationError("货款尚未支付成功")
    from apps.loans.services import has_open_dispute

    if has_open_dispute(transfer_id=transfer_id):
        raise ValidationError("存在未解决争议，暂缓结算")

    business_id = _business_id(transfer.id, PaymentOperation.Kind.SETTLEMENT, PURPOSE_SALE)
    op, created = PaymentOperation.objects.get_or_create(
        business_id=business_id,
        defaults=dict(
            transfer=transfer,
            kind=PaymentOperation.Kind.SETTLEMENT,
            purpose=PURPOSE_SALE,
            amount=transfer.amount,
            status=PaymentOperation.Status.SETTLING,
        ),
    )
    return op


@transaction.atomic
def request_refund(*, transfer_id, reason):
    """申请原路退款（CP-BR-22、CP-R-25、CP-ST-23/24）。

    服务内再次校验付款、争议和取消、撤销、归还或赔偿结清结果。
    """
    from apps.transfers.models import Transfer

    transfer = Transfer.objects.select_for_update().get(pk=transfer_id)

    if transfer.kind == Transfer.Kind.DONATION:
        raise ValidationError("赠送流转不涉及退款")
    cancelled = transfer.status in (Transfer.Status.CANCELLED, Transfer.Status.REVOKED)
    if transfer.kind == Transfer.Kind.SALE:
        purpose = PURPOSE_SALE
        if not cancelled:
            raise ValidationError("买卖退款仅限取消或协商撤销生效后")
    else:
        purpose = PURPOSE_DEPOSIT
        if not cancelled:
            from apps.loans.models import BorrowAgreement

            if not BorrowAgreement.objects.filter(
                transfer=transfer,
                status__in=(BorrowAgreement.Status.RETURNED, BorrowAgreement.Status.COMPENSATED),
            ).exists():
                raise ValidationError("押金退款须在归还、赔偿结清或取消撤销后办理")

    if not is_paid(transfer_id=transfer_id, purpose=purpose):
        raise ValidationError("尚未付款成功，不能退款")

    from apps.loans.services import has_open_dispute

    if has_open_dispute(transfer_id=transfer_id):
        raise ValidationError("相关争议还在处理中，退款已暂停。")

    paid = transfer.payment_operations.get(
        kind=PaymentOperation.Kind.PAYMENT, purpose=purpose, status=PaymentOperation.Status.PAID
    )
    business_id = _business_id(transfer.id, PaymentOperation.Kind.REFUND, purpose)
    op, _ = PaymentOperation.objects.get_or_create(
        business_id=business_id,
        defaults=dict(
            transfer=transfer,
            kind=PaymentOperation.Kind.REFUND,
            purpose=purpose,
            amount=paid.amount,
            reason=reason,
            status=PaymentOperation.Status.REFUNDING,
        ),
    )
    return op  # 幂等：已存在则返回既有记录，不重复退款


@transaction.atomic
def apply_simulated_receipt(*, operation_id, result):
    """受控模拟回执：仅由管理命令/受控工具产生（共同约定 §4）。

    ``result`` 为 success / failure / unknown。回执只对「处理中/未知」的操作生效，
    已到账/失败等终态操作不因重复回执回退（重复回执按同一业务标识去重）。
    """
    if result not in (RECEIPT_SUCCESS, RECEIPT_FAILURE, RECEIPT_UNKNOWN):
        raise ValidationError("无效回执结果")

    from apps.transfers.models import Transfer

    transfer_id = PaymentOperation.objects.values_list("transfer_id", flat=True).get(
        pk=operation_id
    )
    transfer = Transfer.objects.select_for_update().get(pk=transfer_id)
    op = PaymentOperation.objects.select_for_update().get(pk=operation_id)
    before = op.status

    if op.status in (PaymentOperation.Status.UNKNOWN, _PROCESSING_BY_KIND[op.kind]) or (
        op.kind == PaymentOperation.Kind.PAYMENT
        and op.status == PaymentOperation.Status.PAY_FAILED
        and transfer.status in (Transfer.Status.CANCELLED, Transfer.Status.REVOKED)
        and result == RECEIPT_SUCCESS
    ):
        if result == RECEIPT_SUCCESS:
            op.status = _SUCCESS_BY_KIND[op.kind]
        elif result == RECEIPT_FAILURE:
            op.status = _FAILURE_BY_KIND[op.kind]
        else:
            op.status = PaymentOperation.Status.UNKNOWN
        op.last_receipt = result
        op.save(update_fields=["status", "last_receipt", "updated_at"])
    if op.status != before:
        _notify_both(transfer, event_key=f"{op.kind}.{op.status}", message=op.get_status_display())
    return op


def _retryable_failed_statuses():
    return [
        PaymentOperation.Status.SETTLE_FAILED,
        PaymentOperation.Status.REFUND_FAILED,
    ]


@transaction.atomic
def reconcile_and_retry(op):
    """对账并重试结算/退款（CP-ST-38、CP-D-09/18）。供 process_payment_operations 使用。

    - 撤销协商或争议处理中暂停重试；
    - 未知结果不盲重试；
    - 失败且 attempts < 3 重新发起并计数，达到上限转人工并通知双方。
    返回状态字符串，便于命令统计。
    """
    from apps.transfers.models import Transfer

    transfer = Transfer.objects.select_for_update().get(pk=op.transfer_id)
    op = PaymentOperation.objects.select_for_update().get(pk=op.pk)

    if transfer.revoke_status == Transfer.RevokeStatus.NEGOTIATING:
        return "paused_revoke"
    from apps.loans.services import has_open_dispute

    if has_open_dispute(transfer_id=transfer.id):
        return "paused_dispute"

    if op.status == PaymentOperation.Status.UNKNOWN:
        return "needs_reconcile"  # 未知先查明，不盲目重试
    if op.status not in _retryable_failed_statuses():
        return None

    if op.attempts < MAX_AUTO_RETRIES:
        op.attempts += 1
        op.status = _PROCESSING_BY_KIND[op.kind]
        op.save(update_fields=["status", "attempts", "updated_at"])
        return "retried"
    else:
        op.status = PaymentOperation.Status.NEEDS_MANUAL
        op.save(update_fields=["status", "updated_at"])
        _notify_both(
            transfer,
            event_key=f"{op.kind}_needs_manual:{op.id}",
            message=f"{op.get_kind_display()}自动重试已达上限，转管理员处理",
        )
        return "needs_manual"


def _notify_both(transfer, *, event_key, message):
    from apps.loans.models import Notification
    from apps.loans.services import notify_transfer

    notify_transfer(
        transfer,
        business_kind=Notification.Business.FUNDS,
        event=event_key,
        title=f"模拟资金 · {message}",
    )
