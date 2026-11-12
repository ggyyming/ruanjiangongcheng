"""物品表单（CP-D-03：公开字段与私密字段；流转类型对应的价格规则）。

图片字段（本轮模块 A）：发布可上传、编辑可保留/替换/移除。
服务端先检查大小与格式，再验证能否解码；通过后以合法格式重新编码并去除 EXIF 等元数据。
"""

import io
import os

from django import forms
from django.core.files.base import ContentFile
from PIL import Image, UnidentifiedImageError

from .models import Item

MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 源文件及最终存储文件均不超过 5 MiB
MAX_IMAGE_SIDE = 4096  # 宽高各不超过 4096 像素


class ItemForm(forms.ModelForm):
    image = forms.ImageField(
        label="物品图片",
        required=False,
        widget=forms.FileInput(attrs={"accept": "image/jpeg,image/png"}),
        help_text="可选，仅支持 JPEG、PNG，不超过 5 MiB，宽高不超过 4096 像素。",
    )
    remove_image = forms.BooleanField(label="移除当前图片", required=False)

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
        labels = {
            "flow_type": "流转方式",
            "deposit_display": "参考押金（元）",
            "contact": "联系方式",
            "location": "具体交付地点",
        }
        help_texts = {"deposit_display": "实际押金由物主和借用者共同确认。"}

    def clean_image(self):
        upload = self.cleaned_data.get("image")
        if upload is None:
            return upload
        if upload.size > MAX_IMAGE_BYTES:
            raise forms.ValidationError("图片不能超过 5 MiB。")
        declared_type = (upload.content_type or "").lower()
        declared_ext = os.path.splitext(upload.name or "")[1].lower()
        try:
            with Image.open(upload) as probe:
                img_format = probe.format
                width, height = probe.size
        except UnidentifiedImageError:
            raise forms.ValidationError("无法识别的图片文件。")
        except OSError:
            raise forms.ValidationError("图片文件已损坏，无法读取。")
        if img_format not in ("JPEG", "PNG"):
            raise forms.ValidationError("仅支持 JPEG、PNG 格式。")
        # 拒绝“仅改后缀”的图片：真实格式须与声明的类型及扩展名一致
        type_match = True
        if declared_type in ("image/jpeg", "image/png"):
            type_match = (declared_type == "image/jpeg") == (img_format == "JPEG")
        ext_match = True
        if declared_ext in (".jpg", ".jpeg", ".png"):
            ext_match = (declared_ext in (".jpg", ".jpeg")) == (img_format == "JPEG")
        if not (type_match and ext_match):
            raise forms.ValidationError("图片真实格式与文件扩展名或类型声明不一致。")
        if width > MAX_IMAGE_SIDE or height > MAX_IMAGE_SIDE:
            raise forms.ValidationError("图片宽高各不能超过 4096 像素。")
        target_format = "JPEG" if img_format == "JPEG" else "PNG"
        try:
            with Image.open(upload) as img:
                if target_format == "JPEG" and img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")
                out = io.BytesIO()
                img.save(out, format=target_format)
        except OSError:
            raise forms.ValidationError("图片文件已损坏，无法读取。")
        data = out.getvalue()
        if len(data) > MAX_IMAGE_BYTES:
            raise forms.ValidationError("图片处理后仍超过 5 MiB。")
        ext = "jpg" if target_format == "JPEG" else "png"
        return ContentFile(data, name=f"item.{ext}")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("remove_image") and cleaned.get("image"):
            self.add_error("remove_image", "移除当前图片和上传新图片不能同时选择。")
        flow_type = cleaned.get("flow_type")
        price = cleaned.get("price")
        deposit = cleaned.get("deposit_display")
        if flow_type == Item.FlowType.SALE:
            if not price:
                self.add_error("price", "出售必须填写价格，且金额须大于零。")
            if deposit is not None:
                self.add_error("deposit_display", "出售物品不填写押金展示")
        elif flow_type == Item.FlowType.GIFT:
            if price is not None or deposit is not None:
                self.add_error("price", "赠送物品不填写价格或押金")
        elif flow_type == Item.FlowType.LOAN:
            if price is not None:
                self.add_error("price", "出借物品不填写出售价格")
            if not deposit:
                self.add_error("deposit_display", "请填写大于零的参考押金。")
        return cleaned
