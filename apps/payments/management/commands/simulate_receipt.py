"""受控模拟回执（共同约定 §4「模拟回执只由受控模拟工具/管理命令产生」）。

用法示例（把 --operation-id 换成实际资金操作 id）：

    uv run python manage.py simulate_receipt --operation-id 3 --result success
    uv run python manage.py simulate_receipt --operation-id 3 --result failure
    uv run python manage.py simulate_receipt --operation-id 3 --result unknown

普通用户没有对应页面入口，不能通过 URL 参数直接写资金到账。
"""

from django.core.management.base import BaseCommand

from apps.payments.services import apply_simulated_receipt


class Command(BaseCommand):
    help = "向指定资金操作写入一条模拟第三方回执（success/failure/unknown）。"

    def add_arguments(self, parser):
        parser.add_argument("--operation-id", type=int, required=True)
        parser.add_argument(
            "--result",
            choices=["success", "failure", "unknown"],
            required=True,
        )

    def handle(self, *args, **options):
        op = apply_simulated_receipt(operation_id=options["operation_id"], result=options["result"])
        self.stdout.write(
            f"操作 #{op.id} 收到模拟回执 {options['result']}，当前状态 {op.get_status_display()}"
        )
