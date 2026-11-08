"""物品表单（CP-D-03：公开字段与私密字段；流转类型对应的价格规则）。"""
from django import forms

from .models import Item


class ItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = [
            "name",
            "category",
            "description",
            "flaws",
            "flow_type",
            "price",
            "deposit_display",
            "owner_nickname",
            "campus_area",
            "contact",
            "location",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "flaws": forms.Textarea(attrs={"rows": 2}),
        }

    def clean(self):
        cleaned = super().clean()
        flow_type = cleaned.get("flow_type")
        price = cleaned.get("price")
        deposit = cleaned.get("deposit_display")
        if flow_type == Item.FlowType.SALE:
            if not price:
                self.add_error("price", "出售必须填写价格")
            if deposit is not None:
                self.add_error("deposit_display", "出售物品不填写押金展示")
        elif flow_type == Item.FlowType.GIFT:
            if price is not None or deposit is not None:
                self.add_error("price", "赠送物品不填写价格或押金")
        elif flow_type == Item.FlowType.LOAN:
            if price is not None:
                self.add_error("price", "出借物品不填写出售价格")
            if not deposit:
                self.add_error("deposit_display", "出借须填写押金展示金额")
        return cleaned
