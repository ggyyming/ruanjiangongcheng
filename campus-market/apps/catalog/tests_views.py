"""物品市场页面测试（CP-R-08、CP-D-03/05/10/11 及本轮模块 A 图片上传/审核/展示）。"""

import os
import tempfile
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image as PILImage

from apps.accounts.models import IdentityApplication
from apps.transfers.models import Application, Transfer

from .models import Item

User = get_user_model()


def make_verified_user(username="u1"):
    user = User.objects.create_user(username=username, password="x123456")
    IdentityApplication.objects.create(
        user=user,
        name=user.username,
        staff_no="20240001",
        department="计算机学院",
        status=IdentityApplication.Status.APPROVED,
    )
    return user


def make_admin():
    return User.objects.create_user(username="admin", password="x123456", is_staff=True)


ITEM_FIELDS = {
    "name": "高等数学教材",
    "category": "教材",
    "description": "九成新",
    "flow_type": "出售",
    "price": "15.00",
    "owner_nickname": "小张",
    "campus_area": "东区宿舍",
    "contact": "QQ 12345",
    "location": "东区食堂门口",
}


class PublishAndReviewTest(TestCase):
    def test_publish_pending_then_review_public(self):
        """CP-R-08/CP-D-05：先审核后公开。"""
        user = make_verified_user()
        self.client.force_login(user)
        resp = self.client.post(reverse("items:create"), ITEM_FIELDS)
        self.assertEqual(resp.status_code, 302)
        item = Item.objects.get()
        self.assertEqual(item.display_status, Item.DisplayStatus.PENDING)

        # 待审核不出现在公开列表，直接访问不可见
        anon = self.client
        anon.logout()
        self.assertNotContains(anon.get(reverse("items:list")), "高等数学教材")
        resp = anon.get(reverse("items:detail", args=[item.id]))
        self.assertEqual(resp.status_code, 403)

        # 管理员通过后公开
        admin = make_admin()
        self.client.force_login(admin)
        self.client.post(reverse("items:review", args=[item.id]), {"approve": "on"})
        anon = self.client
        anon.logout()
        resp = anon.get(reverse("items:list"))
        self.assertContains(resp, "高等数学教材")

    def test_public_detail_hides_private_fields(self):
        """CP-D-03：联系方式与具体地点不公开。"""
        user = make_verified_user()
        item = Item.objects.create(
            owner=user, display_status=Item.DisplayStatus.AVAILABLE, **ITEM_FIELDS
        )
        resp = self.client.get(reverse("items:detail", args=[item.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "QQ 12345")
        self.assertNotContains(resp, "东区食堂门口")

    def test_owner_detail_hides_private_fields_before_reservation(self):
        user = make_verified_user()
        item = Item.objects.create(
            owner=user, display_status=Item.DisplayStatus.AVAILABLE, **ITEM_FIELDS
        )
        self.client.force_login(user)
        resp = self.client.get(reverse("items:detail", args=[item.id]))
        self.assertNotContains(resp, "QQ 12345")

    def test_reject_requires_reason(self):
        user = make_verified_user()
        item = Item.objects.create(owner=user, **ITEM_FIELDS)
        admin = make_admin()
        self.client.force_login(admin)
        self.client.post(reverse("items:review", args=[item.id]), {})
        item.refresh_from_db()
        self.assertEqual(item.display_status, Item.DisplayStatus.PENDING)

    def test_reject_then_edit_resubmit(self):
        """CP-D-10：驳回后修改重提，重新待审核。"""
        user = make_verified_user()
        item = Item.objects.create(owner=user, **ITEM_FIELDS)
        admin = make_admin()
        self.client.force_login(admin)
        self.client.post(reverse("items:review", args=[item.id]), {"reason": "描述不实"})
        item.refresh_from_db()
        self.assertEqual(item.display_status, Item.DisplayStatus.REJECTED)

        self.client.force_login(user)
        fields = dict(ITEM_FIELDS, description="九成新，无笔记")
        self.client.post(reverse("items:edit", args=[item.id]), fields)
        item.refresh_from_db()
        self.assertEqual(item.display_status, Item.DisplayStatus.PENDING)

    def test_edit_approved_item_requires_review_again(self):
        """CP-D-10：已通过审核的物品修改后重新待审，通过前隐藏。"""
        user = make_verified_user()
        item = Item.objects.create(
            owner=user, display_status=Item.DisplayStatus.AVAILABLE, **ITEM_FIELDS
        )
        self.client.force_login(user)
        self.client.post(reverse("items:edit", args=[item.id]), ITEM_FIELDS)
        item.refresh_from_db()
        self.assertEqual(item.display_status, Item.DisplayStatus.PENDING)
        anon = self.client
        anon.logout()
        self.assertNotContains(anon.get(reverse("items:list")), "高等数学教材")

    def test_offline_and_relist_requires_review(self):
        """CP-D-11：下架后物主申请重上架，重新审核通过才开放。"""
        user = make_verified_user()
        item = Item.objects.create(
            owner=user, display_status=Item.DisplayStatus.AVAILABLE, **ITEM_FIELDS
        )
        self.client.force_login(user)
        self.client.post(reverse("items:offline", args=[item.id]))
        item.refresh_from_db()
        self.assertEqual(item.display_status, Item.DisplayStatus.OFFLINE)

        self.client.post(reverse("items:relist", args=[item.id]))
        item.refresh_from_db()
        self.assertEqual(item.display_status, Item.DisplayStatus.PENDING)
        anon = self.client
        anon.logout()
        self.assertNotContains(anon.get(reverse("items:list")), "高等数学教材")


class PermissionTest(TestCase):
    def test_non_owner_cannot_edit(self):
        user = make_verified_user("u1")
        other = make_verified_user("u2")
        item = Item.objects.create(owner=user, **ITEM_FIELDS)
        self.client.force_login(other)
        resp = self.client.post(reverse("items:edit", args=[item.id]), ITEM_FIELDS)
        self.assertEqual(resp.status_code, 403)

    def test_non_staff_cannot_review(self):
        user = make_verified_user()
        item = Item.objects.create(owner=user, **ITEM_FIELDS)
        self.client.force_login(user)
        resp = self.client.get(reverse("items:review", args=[item.id]))
        self.assertEqual(resp.status_code, 302)  # user_passes_test 跳转登录

    def test_sale_requires_price(self):
        user = make_verified_user()
        self.client.force_login(user)
        resp = self.client.post(reverse("items:create"), dict(ITEM_FIELDS, price=""))
        self.assertEqual(Item.objects.count(), 0)
        self.assertContains(resp, "出售必须填写价格")


def make_image_upload(fmt="PNG", size=(64, 64), color=(30, 120, 70), name=None):
    """动态生成测试图片（不提交素材文件）。"""
    buf = BytesIO()
    PILImage.new("RGB", size, color).save(buf, format=fmt)
    ext = "png" if fmt == "PNG" else "jpg"
    return SimpleUploadedFile(name or f"photo.{ext}", buf.getvalue(), content_type=f"image/{ext}")


class ItemImageTest(TestCase):
    """本轮模块 A：物品图片上传、审核与展示（验收 A1–A5）。"""

    def setUp(self):
        self.temp_media = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.temp_media.name)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        self.temp_media.cleanup()

    def image_url(self, item):
        return reverse("items:image", args=[item.id, item.image_key])

    def publish_with_image(self):
        user = make_verified_user()
        self.client.force_login(user)
        resp = self.client.post(
            reverse("items:create"), {**ITEM_FIELDS, "image": make_image_upload()}
        )
        self.assertEqual(resp.status_code, 302)
        return user, Item.objects.get()

    def approve(self, item):
        admin = getattr(self, "_admin", None)
        if admin is None:
            admin = make_admin()
            self._admin = admin
        self.client.force_login(admin)
        self.client.post(reverse("items:review", args=[item.id]), {"approve": "on"})
        item.refresh_from_db()

    def test_publish_image_pending_then_public(self):
        """A1：待审图对访客不可访问，物主与管理员能预览；审核通过后公开并出现在列表。"""
        user, item = self.publish_with_image()
        self.assertTrue(item.image)
        url = self.image_url(item)

        self.client.force_login(user)
        self.assertEqual(self.client.get(url).status_code, 200)

        admin = make_admin()
        self.client.force_login(admin)
        self.assertEqual(self.client.get(url).status_code, 200)

        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 403)

        self.client.force_login(admin)
        self.client.post(reverse("items:review", args=[item.id]), {"approve": "on"})
        item.refresh_from_db()
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertContains(self.client.get(reverse("items:list")), url)

    def test_replace_image_old_url_invalid(self):
        """A2：更换图片后旧地址失效；新图重新审核通过后才公开。"""
        user, item = self.publish_with_image()
        self.approve(item)
        old_key = item.image_key
        old_name = item.image.name

        self.client.force_login(user)
        resp = self.client.post(
            reverse("items:edit", args=[item.id]),
            {**ITEM_FIELDS, "image": make_image_upload(color=(200, 20, 20), name="photo2.png")},
        )
        self.assertEqual(resp.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.display_status, Item.DisplayStatus.PENDING)
        new_key = item.image_key
        self.assertNotEqual(old_key, new_key)
        # 替换后原文件删除、新文件已写入
        self.assertFalse(default_storage.exists(old_name))
        self.assertTrue(default_storage.exists(item.image.name))

        # 待审：访客对旧地址 404（key 失效）、对新地址 403（未公开）
        self.client.logout()
        old_url = reverse("items:image", args=[item.id, old_key])
        new_url = reverse("items:image", args=[item.id, new_key])
        self.assertEqual(self.client.get(old_url).status_code, 404)
        self.assertEqual(self.client.get(new_url).status_code, 403)

        # 再次审核通过后新图公开，旧地址仍失效
        self.approve(item)
        self.assertEqual(self.client.get(new_url).status_code, 200)
        self.assertEqual(self.client.get(old_url).status_code, 404)

    def test_edit_without_file_keeps_image(self):
        """A3：编辑时不选文件表示保留原图，仍按现有规则重审。"""
        user, item = self.publish_with_image()
        self.approve(item)
        old_name = item.image.name
        self.client.force_login(user)
        resp = self.client.post(reverse("items:edit", args=[item.id]), ITEM_FIELDS)
        self.assertEqual(resp.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.display_status, Item.DisplayStatus.PENDING)
        self.assertEqual(item.image.name, old_name)
        self.assertTrue(default_storage.exists(old_name))

    def test_edit_remove_image(self):
        """A3：主动移除图片，文件删除、旧地址失效。"""
        user, item = self.publish_with_image()
        self.approve(item)
        old_name = item.image.name
        self.client.force_login(user)
        resp = self.client.post(
            reverse("items:edit", args=[item.id]), {**ITEM_FIELDS, "remove_image": "on"}
        )
        self.assertEqual(resp.status_code, 302)
        item.refresh_from_db()
        self.assertFalse(item.image)
        self.assertFalse(default_storage.exists(old_name))
        removed_url = reverse("items:image", args=[item.id, os.path.basename(old_name)])
        self.assertEqual(self.client.get(removed_url).status_code, 404)

    def test_invalid_images_rejected_image_unchanged(self):
        """A4：超限、损坏、仅改后缀、超大尺寸的图片均被拒绝，已有图片与记录保持一致。"""
        user, item = self.publish_with_image()
        old_name = item.image.name
        self.client.force_login(user)
        png_bytes = BytesIO()
        PILImage.new("RGB", (64, 64), (1, 2, 3)).save(png_bytes, format="PNG")
        # 超过 5 MiB 的真实 PNG（随机字节无法压缩，且不依赖 Pillow 已移除的 effect_* 接口）
        noise_buf = BytesIO()
        PILImage.frombytes("RGB", (2000, 2000), os.urandom(2000 * 2000 * 3)).save(
            noise_buf, format="PNG"
        )
        self.assertGreater(len(noise_buf.getvalue()), 5 * 1024 * 1024)

        cases = [
            (
                SimpleUploadedFile("big.png", noise_buf.getvalue(), content_type="image/png"),
                "不能超过 5 MiB",
            ),
            (
                SimpleUploadedFile("bad.jpg", b"not an image", content_type="image/jpeg"),
                None,  # Django ImageField 默认“无效图片”文案，按表单错误字段断言
            ),
            (
                SimpleUploadedFile("fake.jpg", png_bytes.getvalue(), content_type="image/jpeg"),
                "与文件扩展名或类型声明不一致",
            ),
            (
                make_image_upload(size=(5000, 5000), name="huge.png"),
                "不能超过 4096 像素",
            ),
        ]
        for upload, message in cases:
            resp = self.client.post(
                reverse("items:edit", args=[item.id]), {**ITEM_FIELDS, "image": upload}
            )
            self.assertEqual(resp.status_code, 200)
            if message:
                self.assertContains(resp, message)
            self.assertIn("image", resp.context["form"].errors)
            item.refresh_from_db()
            self.assertEqual(item.image.name, old_name)
            self.assertTrue(default_storage.exists(old_name))

    def test_reserved_item_image_rules(self):
        """A5：预留期间接收方可看已通过审核的当前图片；物主换图被拒绝。"""
        user, item = self.publish_with_image()
        self.approve(item)
        buyer = make_verified_user("buyer")
        app = Application.objects.create(item=item, applicant=buyer, kind=Application.Kind.SALE)
        Transfer.objects.create(
            application=app,
            item=item,
            owner=user,
            recipient=buyer,
            kind=Transfer.Kind.SALE,
            status=Transfer.Status.RESERVED,
        )
        url = self.image_url(item)
        self.client.force_login(buyer)
        self.assertEqual(self.client.get(url).status_code, 200)

        old_name = item.image.name
        self.client.force_login(user)
        resp = self.client.post(
            reverse("items:edit", args=[item.id]),
            {**ITEM_FIELDS, "image": make_image_upload(color=(9, 9, 9))},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "正在流转")
        item.refresh_from_db()
        self.assertEqual(item.image.name, old_name)
        self.assertEqual(item.display_status, Item.DisplayStatus.AVAILABLE)

    def test_offline_item_image_hidden_from_visitors(self):
        """A5：下架后访客用原图片地址也无法访问；物主仍可查看。"""
        user, item = self.publish_with_image()
        self.approve(item)
        url = self.image_url(item)
        self.client.force_login(user)
        self.client.post(reverse("items:offline", args=[item.id]))
        item.refresh_from_db()
        self.assertEqual(item.display_status, Item.DisplayStatus.OFFLINE)

        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(user)
        self.assertEqual(self.client.get(url).status_code, 200)
