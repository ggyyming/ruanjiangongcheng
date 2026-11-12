"""流转页面表单：只承载用户输入，业务校验在 services 中完成。"""

from django import forms

from .models import Revocation


class ReasonForm(forms.Form):
    """取消 / 发起撤销协商等需要记录原因的操作。"""

    reason = forms.CharField(
        label="原因",
        widget=forms.Textarea(attrs={"rows": 2}),
        required=True,
    )


class DirectionForm(forms.Form):
    """协商撤销中的物品去向声明：未交出或已退回（CP-BR-10）。"""

    direction = forms.ChoiceField(
        label="物品去向",
        choices=Revocation.Direction.choices,
        widget=forms.RadioSelect,
    )
