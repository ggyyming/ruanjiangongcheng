"""流转申请、流转（预留关系 + 交付事实）与状态迁移审计留痕。

本包（transfers）负责：多人申请、物主唯一预留、双方分别确认交付、交付前取消。
物品（Item）与校内身份（IdentityApplication）分别由 apps.catalog / apps.accounts 拥有，
这里只通过字符串外键 ``'catalog.Item'`` 引用，不复制其字段（共同约定 §2）。

状态口径与需求一一对应，见 docs/校园物品流转平台/附件/01_规则与数据/状态转换说明.md：

- Application：待选择 -> 已选中 | 已关闭 | 已取消
- Transfer：已预留 -> 已成交(买卖) | 赠送完成 | 已借出(借用) | 已撤销 | 已取消
"""

from django.conf import settings
from django.db import models


class Application(models.Model):
    """流转申请：用户对物品发起的购买 / 受赠 / 借用申请（CP-R-09、CP-ST-03/04）。"""

    class Kind(models.TextChoices):
        SALE = "sale", "购买"
        DONATION = "donation", "受赠"
        BORROW = "borrow", "借用"

    class Status(models.TextChoices):
        PENDING = "pending", "待选择"
        SELECTED = "selected", "已选中"
        CLOSED = "closed", "已关闭"
        CANCELLED = "cancelled", "已取消"

    item = models.ForeignKey("catalog.Item", on_delete=models.CASCADE, related_name="applications")
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="applications"
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    close_reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # 同一物品同一申请人只保留一条待选择申请，防止重复申请
            models.UniqueConstraint(
                fields=["item", "applicant"],
                # Status.PENDING
                condition=models.Q(status="pending"),
                name="transfers_application_pending_unique",
            )
        ]

    def __str__(self):
        return (
            f"#{self.pk} {self.get_kind_display()} "
            f"{self.applicant_id}->{self.item_id} ({self.get_status_display()})"
        )


class Transfer(models.Model):
    """预留关系 + 交付事实（共同约定 §2：一个被选中申请产生一笔 Transfer）。

    ``amount`` 为本次流转固化金额：买卖为货款、借用为押金、赠送为空。
    预留后固化，不随物品后续编辑变化（CP-BR-20/21、CP-D-08）。
    借用 Transfer 对应 C 的一条 Loan，借出双确认后由 C 的 ``start_loan`` 承接。
    """

    class Kind(models.TextChoices):
        SALE = "sale", "买卖"
        DONATION = "donation", "赠送"
        BORROW = "borrow", "借用"

    class Status(models.TextChoices):
        RESERVED = "reserved", "已预留"
        COMPLETED = "completed", "已成交"  # 买卖双方确认交付
        DONATION_COMPLETED = "donation_completed", "赠送完成"
        BORROWED = "borrowed", "已借出"  # 借用双方确认借出，进入借用中（由 C 承接）
        CANCELLED = "cancelled", "已取消"  # 交付前取消
        REVOKED = "revoked", "已撤销"  # 协商撤销生效

    class RevokeStatus(models.TextChoices):
        NONE = "none", "无"
        NEGOTIATING = "negotiating", "撤销协商中"
        REVOKED = "revoked", "已撤销"

    application = models.OneToOneField(
        Application, on_delete=models.CASCADE, related_name="transfer"
    )
    item = models.ForeignKey("catalog.Item", on_delete=models.CASCADE, related_name="transfers")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="owned_transfers",
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="received_transfers",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="买卖为货款、借用为押金、赠送为空；预留时固化",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RESERVED)
    revoke_status = models.CharField(
        max_length=16, choices=RevokeStatus.choices, default=RevokeStatus.NONE
    )

    reserved_at = models.DateTimeField(auto_now_add=True)
    # 双方各自独立的交付确认记录（CP-BR-07：两方分别确认）
    owner_confirmed_at = models.DateTimeField(null=True, blank=True)
    recipient_confirmed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            # 同一物品同时最多一笔进行中流转（已预留或已借出）
            models.UniqueConstraint(
                fields=["item"],
                # Status.RESERVED / Status.BORROWED
                condition=models.Q(status__in=["reserved", "borrowed"]),
                name="transfers_transfer_one_active_per_item",
            )
        ]

    def __str__(self):
        return (
            f"#{self.pk} {self.get_kind_display()} "
            f"item={self.item_id} ({self.get_status_display()})"
        )

    @property
    def both_confirmed(self):
        return self.owner_confirmed_at is not None and self.recipient_confirmed_at is not None


class Revocation(models.Model):
    """协商撤销记录（CP-R-12、CP-BR-09/10、CP-ST-16/17/34）。

    数据字典「撤销与退回确认」：原流转、原因、双方同意、未交出或退回的双方声明。
    ``Transfer.revoke_status`` 为当前协商状态的快速标志，本模型保存细节记录。
    """

    class Side(models.TextChoices):
        OWNER = "owner", "物主"
        RECIPIENT = "recipient", "获选接收方"

    class Direction(models.TextChoices):
        NOT_HANDED_OVER = "not_handed_over", "未交出"
        RETURNED = "returned", "已退回"

    transfer = models.OneToOneField(Transfer, on_delete=models.CASCADE, related_name="revocation")
    initiator = models.CharField(max_length=16, choices=Side.choices)
    reason = models.TextField()

    owner_direction = models.CharField(
        max_length=16, choices=Direction.choices, null=True, blank=True
    )
    owner_direction_at = models.DateTimeField(null=True, blank=True)
    recipient_direction = models.CharField(
        max_length=16, choices=Direction.choices, null=True, blank=True
    )
    recipient_direction_at = models.DateTimeField(null=True, blank=True)

    # 双方同意撤销（发起方在发起时即视为同意）
    owner_agreed_at = models.DateTimeField(null=True, blank=True)
    recipient_agreed_at = models.DateTimeField(null=True, blank=True)

    # 双方撤回撤销申请（CP-ST-34）
    owner_withdrawn_at = models.DateTimeField(null=True, blank=True)
    recipient_withdrawn_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"撤销协商 #{self.transfer_id} by {self.initiator}"


class TransferLog(models.Model):
    """流转状态迁移审计留痕（CP-Q-04：重要决定保留原因与关联记录）。"""

    transfer = models.ForeignKey(Transfer, on_delete=models.CASCADE, related_name="logs")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
    )
    action = models.CharField(max_length=32)
    from_status = models.CharField(max_length=16, blank=True, default="")
    to_status = models.CharField(max_length=16, blank=True, default="")
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"#{self.pk} {self.action} {self.transfer_id} {self.from_status}->{self.to_status}"
