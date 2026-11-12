from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "依次处理付款超时、模拟资金对账及重试、借用逾期。"

    def handle(self, *args, **options):
        for command in (
            "process_payment_timeouts",
            "process_payment_operations",
            "scan_overdue_loans",
        ):
            call_command(command, stdout=self.stdout)
