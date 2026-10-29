from django import forms

from .models import Dispute

DATETIME_INPUT_FORMATS = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"]


class DueDateForm(forms.Form):
    due_at = forms.DateTimeField(
        label="约定归还时间（北京时间）",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        input_formats=DATETIME_INPUT_FORMATS,
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
