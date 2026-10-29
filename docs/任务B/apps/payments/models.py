"""模拟资金：支付 / 结算 / 退款三类处理，与实物流转状态分离。

资金全部模拟，不接真实支付（CP-R-19/20）。状态口径见状态转换说明 CP-ST-20~24/37/38
与业务细则 CP-D-08/09/17/18：

- 支付：未支付 -> 支付处理中 -> 已支付 / 支付失败 / 未知
- 结算：未发起结算 -> 结算处理中 -> 已结算到账 / 结算失败 / 未知
- 退款：未发起退款 -> 退款处理中 -> 已退款到账 / 退款失败 / 未知

三类处理、用途（货款/押金）及实物状态分别表示，无钱包余额。同一业务标识防重复处理，
重试次数（不含首次）留痕；发起不等于到账。
"""

from django.db import models


class PaymentOperation(models.Model):
    """一笔资金处理。"""

    class Kind(models.TextChoices):
        PAYMENT = "payment", "支付"  # 买家付货款 / 借用者付押金
        SETTLEMENT = "settlement", "结算"  # 平台向卖家结算货款
        REFUND = "refund", "退款"  # 原路退款

    class Purpose(models.TextChoices):
        SALE = "sale", "货款"
        DEPOSIT = "deposit", "押金"

    class Status(models.TextChoices):
        # 支付
        UNPAID = "unpaid", "未支付"
        PAYING = "paying", "支付处理中"
        PAID = "paid", "已支付"
        PAY_FAILED = "pay_failed", "支付失败"
        # 结算
        UNSETTLED = "unsettled", "未发起结算"
        SETTLING = "settling", "结算处理中"
        SETTLED = "settled", "已结算到账"
        SETTLE_FAILED = "settle_failed", "结算失败"
        # 退款
        UNREFUNDED = "unrefunded", "未发起退款"
        REFUNDING = "refunding", "退款处理中"
        REFUNDED = "refunded", "已退款到账"
        REFUND_FAILED = "refund_failed", "退款失败"
        # 通用
        UNKNOWN = "unknown", "结果未知"
        NEEDS_MANUAL = "needs_manual", "转人工处理"

    transfer = models.ForeignKey(
        "transfers.Transfer",
        on_delete=models.CASCADE,
        related_name="payment_operations",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    purpose = models.CharField(max_length=16, choices=Purpose.choices)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=16, choices=Status.choices)
    # 同一业务标识，防重复处理（CP-D-09/18「使用同一业务标识核对并记录」）
    business_id = models.CharField(max_length=64, unique=True)
    attempts = models.PositiveSmallIntegerField(default=0, help_text="自动重试次数（不含首次）")
    last_receipt = models.CharField(
        max_length=32, blank=True, default="", help_text="最近一次模拟回执结果"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return (
            f"#{self.pk} {self.get_kind_display()}/{self.get_purpose_display()} "
            f"transfer={self.transfer_id} ({self.get_status_display()})"
        )
