"""物品市场数据模型（A 包）。

对应需求 CP-R-08，细则 CP-D-03/05/10/11。
- CP-D-03：公开名称、类别、描述、图片、流转方式、售价或押金、物主昵称、校内大致区域；
  姓名、学号或工号不公开；联系方式和具体地点仅预留后双方可见（独立字段存储）。
- CP-D-05：先审核后公开；不通过记录原因。
- CP-D-10：有进行中流转禁止修改（修改入口由 B 的流转事实配合判断，本模型不保存流转状态）；
  其余修改后转待审核，通过前隐藏。
- CP-D-11：退回/归还后不自动开放，由物主申请重新上架并重新审核。

ponytail: 图片上传（图片字段与大小/类型限制）在 A1 阶段实现，M0 不建图片字段。
"""

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Item(models.Model):
    class FlowType(models.TextChoices):
        SALE = "出售", "出售"
        GIFT = "赠送", "赠送"
        LOAN = "出借", "出借"

    class DisplayStatus(models.TextChoices):
        DRAFT = "草稿", "草稿"
        PENDING = "待审核", "待审核"
        AVAILABLE = "可申请", "可申请"
        REJECTED = "已驳回", "已驳回"
        OFFLINE = "已下架", "已下架"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="items"
    )
    name = models.CharField("物品名称", max_length=100)
    category = models.CharField("类别", max_length=50)
    description = models.CharField("描述", max_length=500)
    flaws = models.CharField("瑕疵说明", max_length=200, blank=True)
    flow_type = models.CharField("流转类型", max_length=10, choices=FlowType.choices)
    price = models.DecimalField(
        "出售价格（元）",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    deposit_display = models.DecimalField(
        "借用押金展示（元）",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="仅作展示；实际押金由双方约定并在 B 的支付目标中固化",
    )
    owner_nickname = models.CharField("物主昵称", max_length=50)
    campus_area = models.CharField("校内大致区域", max_length=50)
    contact = models.CharField("联系方式（私密）", max_length=100, blank=True)
    location = models.CharField("具体交付地点（私密）", max_length=100, blank=True)
    display_status = models.CharField(
        "展示状态", max_length=10, choices=DisplayStatus.choices, default=DisplayStatus.PENDING
    )
    review_reason = models.CharField("审核结论或下架原因", max_length=200, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="item_reviews",
        verbose_name="审核管理员",
    )
    reviewed_at = models.DateTimeField("审核时间", null=True, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("修改时间", auto_now=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"{self.id} {self.name} {self.display_status}"


class ItemAvailabilityChange(models.Model):
    """物品公开资格变更记录（共同约定：历史不改写）。"""

    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="availability_changes")
    available = models.BooleanField("变更后是否可申请")
    reason = models.CharField("原因", max_length=200)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="availability_changes",
    )
    created_at = models.DateTimeField("变更时间", auto_now_add=True)

    class Meta:
        ordering = ["-id"]
