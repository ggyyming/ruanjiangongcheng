from decimal import Decimal

from django import forms
from PIL import Image

from .models import Dispute, DisputeAttachment

DATETIME_INPUT_FORMATS = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"]


class DueDateForm(forms.Form):
    due_at = forms.DateTimeField(
        label="约定归还时间（北京时间）",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        input_formats=DATETIME_INPUT_FORMATS,
    )
    deposit_amount = forms.DecimalField(
        label="押金金额（元）",
        min_value=Decimal("0.01"),
        max_digits=10,
        decimal_places=2,
        required=False,
        help_text="留空保留当前金额。",
    )


class ExtensionForm(forms.Form):
    proposed_due_at = forms.DateTimeField(
        label="申请延长至（北京时间）",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        input_formats=DATETIME_INPUT_FORMATS,
    )


class DisputeForm(forms.Form):
    kind = forms.ChoiceField(label="争议类型", choices=Dispute.Kind.choices)
    description = forms.CharField(label="情况说明", widget=forms.Textarea(attrs={"rows": 4}))
    materials = forms.CharField(
        label="材料说明（可选）",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="仅本次当事双方及负责处理的管理员可见。",
    )


class PlanForm(forms.Form):
    plan = forms.CharField(
        label="赔偿或退款方案",
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="记录方案不等于已履行，也不代表争议已关闭。",
    )


class AdminCloseForm(forms.Form):
    resolution = forms.CharField(
        label="管理员处理结论",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )


class DisputeAttachmentForm(forms.Form):
    file = forms.ImageField(
        label="图片证据",
        help_text="JPEG 或 PNG，不超过 5 MiB，宽高各不超过 4096 像素。",
    )

    def clean_file(self):
        upload = self.cleaned_data["file"]
        if upload.size > DisputeAttachment.MAX_BYTES:
            raise forms.ValidationError("图片不能超过 5 MiB。")
        upload.seek(0)
        with Image.open(upload) as image:
            image_format = image.format
            width, height = image.size
        upload.seek(0)
        if image_format not in DisputeAttachment.FORMATS:
            raise forms.ValidationError("只接受 JPEG 或 PNG 图片。")
        if width > DisputeAttachment.MAX_DIMENSION or height > DisputeAttachment.MAX_DIMENSION:
            raise forms.ValidationError("图片宽高各不能超过 4096 像素。")
        upload.image_format = image_format
        return upload
