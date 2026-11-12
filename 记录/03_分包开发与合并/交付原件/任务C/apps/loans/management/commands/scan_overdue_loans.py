from django.core.management.base import BaseCommand

from apps.loans.services import scan_overdue


class Command(BaseCommand):
    help = "标记逾期借用、站内提醒双方、限制借用者并通知流转包关闭未选定申请。"

    def handle(self, *args, **options):
        marked = scan_overdue()
        self.stdout.write(self.style.SUCCESS(f"已标记逾期借用 {marked} 笔。"))
