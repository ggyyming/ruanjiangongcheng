"""资金对账与重试扫描（CP-ST-38、CP-D-09/18）。

1. 迟到支付：已取消/已撤销的流转若发现实际入账（已支付）且无争议，走既有退款条件。
2. 结算/退款失败或未知：对账；失败且未达上限自动重试，未知不盲重试，撤销协商/争议期间暂停。

可重复执行，同一业务标识防重复处理。
"""

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand

from apps.payments.models import PaymentOperation
from apps.payments.services import (
    PURPOSE_DEPOSIT,
    PURPOSE_SALE,
    is_paid,
    reconcile_and_retry,
    request_refund,
)
from apps.transfers.models import Transfer


class Command(BaseCommand):
    help = "核对并重试失败/未知的结算与退款，处理取消后的迟到支付退款。"

    def handle(self, *args, **options):
        # 1) 迟到支付退款
        late_refunds = 0
        for transfer in Transfer.objects.filter(
            status__in=[Transfer.Status.CANCELLED, Transfer.Status.REVOKED]
        ).select_related("application"):
            if transfer.kind == Transfer.Kind.DONATION:
                continue
            purpose = PURPOSE_DEPOSIT if transfer.kind == Transfer.Kind.BORROW else PURPOSE_SALE
            if not is_paid(transfer_id=transfer.id, purpose=purpose):
                continue
            try:
                request_refund(
                    transfer_id=transfer.id,
                    reason="订单取消后发现实际入账，按有效取消退款条件处理（CP-D-17）",
                )
            except ValidationError:
                continue  # 有争议或资格不符，跳过该笔（不中断扫描）
            late_refunds += 1

        # 2) 结算/退款失败或未知 -> 对账 + 重试
        ops = PaymentOperation.objects.filter(
            kind__in=[PaymentOperation.Kind.SETTLEMENT, PaymentOperation.Kind.REFUND],
            status__in=[
                PaymentOperation.Status.SETTLE_FAILED,
                PaymentOperation.Status.REFUND_FAILED,
                PaymentOperation.Status.UNKNOWN,
            ],
        ).select_related("transfer")

        stats = {"retried": 0, "needs_manual": 0, "paused": 0, "needs_reconcile": 0}
        for op in ops:
            result = reconcile_and_retry(op)
            if result in ("paused_revoke", "paused_dispute"):
                stats["paused"] += 1
            elif result == "needs_manual":
                stats["needs_manual"] += 1
            elif result == "needs_reconcile":
                stats["needs_reconcile"] += 1
            elif result == "retried":
                stats["retried"] += 1

        self.stdout.write(
            f"资金扫描：迟到支付退款 {late_refunds} 笔；"
            f"重试 {stats['retried']}，转人工 {stats['needs_manual']}，"
            f"暂停 {stats['paused']}，待对账 {stats['needs_reconcile']}"
        )
