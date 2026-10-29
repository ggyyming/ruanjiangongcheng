"""账号与认证表单（CP-D-01：姓名、学号或工号、院系或部门，不上传证件图片）。"""
from django import forms

from .models import IdentityApplication


class IdentityForm(forms.ModelForm):
    class Meta:
        model = IdentityApplication
        fields = ["name", "staff_no", "department"]
        labels = {
            "name": "姓名",
            "staff_no": "学号或工号",
            "department": "院系或部门",
        }


class ReviewForm(forms.Form):
    approve = forms.BooleanField(required=False, label="审核通过")
    reason = forms.CharField(
        required=False, label="结论/驳回原因", widget=forms.Textarea(attrs={"rows": 3})
    )

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("approve") and not cleaned.get("reason"):
            raise forms.ValidationError("驳回时必须填写原因")
        return cleaned


class RevokeForm(forms.Form):
    reason = forms.CharField(label="撤销原因", widget=forms.Textarea(attrs={"rows": 3}))

    def clean_reason(self):
        reason = self.cleaned_data["reason"].strip()
        if not reason:
            raise forms.ValidationError("撤销认证必须填写原因")
        return reason
