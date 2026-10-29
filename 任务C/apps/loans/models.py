from django.conf import settings
from django.db import models


class BorrowAgreement(models.Model):
    """一次借用从获得预留到归还或赔偿结清的完整记录（CP-R-03/04/14-18/26/27）。"""

    class Status(models.TextChoices):
        PENDING_DELIVERY = "pending_delivery", "待交付"
        ACTIVE = "active", "借用中"
        AWAITING_RETURN = "awaiting_return", "待另一方归还确认"
        RETURNED = "returned", "已归还"
        DISPUTED = "disputed", "争议处理中"
        COMPENSATED = "compensated", "赔偿结清"
        CANCELLED = "cancelled", "已取消"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="loans_as_owner",
        verbose_name="物主",
    )
    borrower = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="loans_as_borrower",
        verbose_name="借用者",
    )
    item_ref = models.CharField(
        max_length=64,
        verbose_name="物品标识",
        help_text="由物品/流转包传入；集成时替换为对应外键。",
    )
    application_ref = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name="流转申请标识",
    )
    item_title = models.CharField(max_length=200, verbose_name="物品名称快照")
    deposit_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="约定押金（元）",
    )

    due_at = models.DateTimeField(null=True, blank=True, verbose_name="有效归还时间")
    due_owner_confirmed_at = models.DateTimeField(
        null=True, blank=True, verbose_name="物主确认归还时间"
    )
    due_borrower_confirmed_at = models.DateTimeField(
        null=True, blank=True, verbose_name="借用者确认归还时间"
    )

    started_at = models.DateTimeField(null=True, blank=True, verbose_name="开始借用时间")
    handed_back_at = models.DateTimeField(null=True, blank=True, verbose_name="借用者确认交还时间")
    return_owner_confirmed_at = models.DateTimeField(
        null=True, blank=True, verbose_name="物主确认收回时间"
    )
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name="归还完成时间")

    overdue_marked_at = models.DateTimeField(null=True, blank=True, verbose_name="标记逾期时间")
    compensated_at = models.DateTimeField(null=True, blank=True, verbose_name="赔偿结清时间")

    deposit_refund_requested_at = models.DateTimeField(
        null=True, blank=True, verbose_name="押金退款申请时间"
    )
    deposit_refund_reason = models.CharField(
        max_length=32, blank=True, default="", verbose_name="押金退款原因"
    )

    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PENDING_DELIVERY,
        verbose_name="借用状态",
    )
    status_before_dispute = models.CharField(
        max_length=32, choices=Status.choices, blank=True, default=""
    )
    cancel_reason = models.CharField(
        max_length=200, blank=True, default="", verbose_name="取消原因"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "借用约定"
        verbose_name_plural = "借用约定"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["borrower", "status"]),
            models.Index(fields=["status", "due_at"]),
        ]

    def __str__(self):
        return f"{self.item_title}（{self.owner} → {self.borrower}）"

    def involves(self, user):
        return bool(
            getattr(user, "is_authenticated", False)
            and user.pk in (self.owner_id, self.borrower_id)
        )

    def is_due_confirmed(self):
        return bool(self.due_at and self.due_owner_confirmed_at and self.due_borrower_confirmed_at)

    def open_dispute(self):
        return self.disputes.filter(status=Dispute.Status.OPEN).first()

    def has_open_dispute(self):
        return self.open_dispute() is not None

    def is_ended(self):
        return self.status in (self.Status.RETURNED, self.Status.COMPENSATED, self.Status.CANCELLED)

    def can_confirm_return(self):
        return self.status in (self.Status.ACTIVE, self.Status.AWAITING_RETURN)


class ExtensionRequest(models.Model):
    """借用延期申请；待批期间不改变有效期限（CP-R-18、CP-D-07/19）。"""

    class Status(models.TextChoices):
        PENDING = "pending", "待物主同意"
        APPROVED = "approved", "已同意"
        REJECTED = "rejected", "已拒绝"

    agreement = models.ForeignKey(
        BorrowAgreement,
        on_delete=models.CASCADE,
        related_name="extensions",
        verbose_name="借用约定",
    )
    previous_due_at = models.DateTimeField(verbose_name="原有效归还时间")
    proposed_due_at = models.DateTimeField(verbose_name="申请的新归还时间")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="loan_extension_requests",
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="loan_extension_decisions",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "延期申请"
        verbose_name_plural = "延期申请"
        ordering = ("-requested_at",)

    def __str__(self):
        return f"{self.agreement} → {self.proposed_due_at:%Y-%m-%d %H:%M}"


class Dispute(models.Model):
    """损坏/丢失争议及赔偿方案，方案、履行、结束意见、关闭分别记录（CP-D-12/14/15/16/22）。"""

    class Kind(models.TextChoices):
        DAMAGE = "damage", "损坏"
        LOSS = "loss", "丢失"

    class Status(models.TextChoices):
        OPEN = "open", "争议处理中"
        CLOSED = "closed", "已关闭"

    agreement = models.ForeignKey(
        BorrowAgreement,
        on_delete=models.CASCADE,
        related_name="disputes",
        verbose_name="借用约定",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices, verbose_name="争议类型")
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="opened_loan_disputes",
    )
    description = models.TextField(verbose_name="情况说明")
    materials = models.TextField(blank=True, default="", verbose_name="材料说明")
    assigned_admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assigned_loan_disputes",
        null=True,
        blank=True,
        verbose_name="负责管理员",
    )

    plan = models.TextField(blank=True, default="", verbose_name="赔偿或退款方案")
    plan_recorded_at = models.DateTimeField(null=True, blank=True)
    plan_recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="loan_dispute_plans",
        null=True,
        blank=True,
    )

    owner_performed_at = models.DateTimeField(null=True, blank=True, verbose_name="物主确认已履行")
    borrower_performed_at = models.DateTimeField(
        null=True, blank=True, verbose_name="借用者确认已履行"
    )
    owner_end_agreed_at = models.DateTimeField(null=True, blank=True, verbose_name="物主同意结束")
    borrower_end_agreed_at = models.DateTimeField(
        null=True, blank=True, verbose_name="借用者同意结束"
    )

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    resolution = models.TextField(blank=True, default="", verbose_name="管理员处理结论")
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="closed_loan_disputes",
        null=True,
        blank=True,
        help_text="空表示双方履行并同意结束后由系统关闭。",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "借用争议"
        verbose_name_plural = "借用争议"
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.get_kind_display()}争议：{self.agreement}"

    def both_performed(self):
        return bool(self.owner_performed_at and self.borrower_performed_at)

    def both_end_agreed(self):
        return bool(self.owner_end_agreed_at and self.borrower_end_agreed_at)

    def is_party(self, user):
        return self.agreement.involves(user)

    def can_view(self, user):
        if self.is_party(user):
            return True
        if not getattr(user, "is_staff", False):
            return False
        return self.assigned_admin_id is None or self.assigned_admin_id == user.pk


class DisputeEvent(models.Model):
    """争议处理留痕；仅用于追溯，不承载业务状态。"""

    dispute = models.ForeignKey(
        Dispute, on_delete=models.CASCADE, related_name="events", verbose_name="争议"
    )
    action = models.CharField(max_length=32, verbose_name="动作")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="loan_dispute_events",
        null=True,
        blank=True,
    )
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "争议处理记录"
        verbose_name_plural = "争议处理记录"
        ordering = ("created_at", "pk")


class BorrowRestriction(models.Model):
    """逾期产生的新增借用限制（CP-R-16/17、CP-BR-14）。"""

    CAUSE_OVERDUE = "overdue"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="borrow_restrictions",
        verbose_name="受限用户",
    )
    cause = models.CharField(
        max_length=32,
        default=CAUSE_OVERDUE,
        verbose_name="限制类型",
        help_text="本包只创建逾期限制；解除时不影响其他原因的限制。",
    )
    reason = models.CharField(max_length=200, verbose_name="限制原因")
    active = models.BooleanField(default=True, verbose_name="限制中")
    created_at = models.DateTimeField(auto_now_add=True)
    released_at = models.DateTimeField(null=True, blank=True, verbose_name="解除时间")

    class Meta:
        verbose_name = "新增借用限制"
        verbose_name_plural = "新增借用限制"
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.user}：{'受限' if self.active else '已解除'}"


class Notification(models.Model):
    """站内通知/消息中心（CP-D-20），不改变任何业务状态。"""

    class Business(models.TextChoices):
        IDENTITY = "identity", "身份审核"
        ITEM = "item", "物品"
        LOAN = "loan", "借用"
        FUNDS = "funds", "资金"
        DISPUTE = "dispute", "争议"
        SYSTEM = "system", "系统"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="loan_notifications",
        verbose_name="接收人",
    )
    business_kind = models.CharField(
        max_length=16, choices=Business.choices, verbose_name="业务类型"
    )
    business_ref = models.CharField(max_length=64, blank=True, default="", verbose_name="业务编号")
    event = models.CharField(max_length=64, verbose_name="事件")
    title = models.CharField(max_length=120, verbose_name="标题")
    body = models.TextField(blank=True, default="", verbose_name="正文")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="发送时间")
    read_at = models.DateTimeField(null=True, blank=True, verbose_name="已读时间")

    class Meta:
        verbose_name = "站内通知"
        verbose_name_plural = "站内通知"
        ordering = ("-created_at", "-pk")
        indexes = [models.Index(fields=["recipient", "read_at"])]

    def __str__(self):
        return f"{self.recipient}：{self.title}"
