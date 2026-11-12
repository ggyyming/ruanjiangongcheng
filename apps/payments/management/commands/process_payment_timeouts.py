"""付款超时扫描（CP-ST-37、CP-D-17）。

对「已预留满 24 小时」的买卖/借用流转，先核对付款结果：
- 确认未付（未发起 / 支付失败）才取消预留；
- 已支付保留；
- 处理中/未知先对账，不直接判未付、不取消。

可重复执行，按当前持久化状态判断，不重复取消。赠送不适用付款超时。
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.transfers.models import Transfer
from apps.transfers.services import cancel_reservation_for_timeout


class Command(BaseCommand):
    help = "核对预留满24小时仍未付款的流转，确认未付才取消。"

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(hours=24)
        overdue = Transfer.objects.filter(
            status=Transfer.Status.RESERVED,
            kind__in=[Transfer.Kind.SALE, Transfer.Kind.BORROW],
            reserved_at__lte=cutoff,
        )

        cancelled = 0
        skipped_paying_or_unknown = 0
        for transfer in overdue:
            if cancel_reservation_for_timeout(transfer, cutoff=cutoff):
                cancelled += 1
            else:
                # 已支付保留；处理中/未知先对账
                skipped_paying_or_unknown += 1

        self.stdout.write(
            f"付款超时扫描：取消 {cancelled} 笔；暂不符合取消条件 {skipped_paying_or_unknown} 笔"
        )
