"""物品市场数据模型（A 包）。

对应需求 CP-R-08，细则 CP-D-03/05/10/11。
- CP-D-03：公开名称、类别、描述、图片、流转方式、售价或押金、物主昵称、校内大致区域；
  姓名、学号或工号不公开；联系方式和具体地点仅预留后双方可见（独立字段存储）。
- CP-D-05：先审核后公开；不通过记录原因。
- CP-D-10：有进行中流转禁止修改（修改入口由 B 的流转事实配合判断，本模型不保存流转状态）；
  其余修改后转待审核，通过前隐藏。
- CP-D-11：退回/归还后不自动开放，由物主申请重新上架并重新审核。

图片：每件物品一张可选图片（本轮模块 A），存储键由服务端生成且不可复用，
替换或移除后旧地址自然失效。历史版本留存为后续任务。
"""

from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


def item_image_path(instance, filename):
    """生成物品图片存储键：每次上传独立 uuid，旧链接不会误指向新图。"""
    ext = Path(filename).suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png"):
        ext = ".jpg"
    return f"items/{uuid4().hex}{ext}"


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
    image = models.ImageField("物品图片", upload_to=item_image_path, null=True, blank=True)
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

    @property
    def image_key(self):
        """图片 URL 中的版本标识；无图或文件缺失时为空字符串。"""
        if not self.image:
            return ""
        return Path(self.image.name).name


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
