"""账号与校内身份认证数据模型（A 包）。

对应需求 CP-R-05/06/07，细则 CP-D-01/02/22。
- CP-D-01：提交姓名、学号或工号、院系或部门，管理员线下核验，不上传证件图片。
- CP-D-02：驳回记录原因，可修改后重新提交，每次重新审核，保留历次审核结果
  （历次结果即同一用户的全部 IdentityApplication 记录）。
"""

from django.conf import settings
from django.db import models


class IdentityApplication(models.Model):
    class Status(models.TextChoices):
        PENDING = "待审核", "待审核"
        APPROVED = "已通过", "已通过"
        REJECTED = "已驳回", "已驳回"
        REVOKED = "已撤销", "已撤销"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="identity_applications"
    )
    name = models.CharField("姓名", max_length=50)
    staff_no = models.CharField("学号或工号", max_length=50)
    department = models.CharField("院系或部门", max_length=100)
    status = models.CharField(
        "审核状态", max_length=10, choices=Status.choices, default=Status.PENDING
    )
    review_reason = models.CharField("审核结论或驳回原因", max_length=200, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="identity_reviews",
        verbose_name="审核管理员",
    )
    reviewed_at = models.DateTimeField("审核时间", null=True, blank=True)
    created_at = models.DateTimeField("提交时间", auto_now_add=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"{self.user_id} {self.name} {self.status}"
