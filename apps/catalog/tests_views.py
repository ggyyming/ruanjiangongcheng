"""物品市场页面测试（CP-R-08、CP-D-03/05/10/11）。"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import IdentityApplication

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

    def test_owner_sees_private_fields(self):
        user = make_verified_user()
        item = Item.objects.create(
            owner=user, display_status=Item.DisplayStatus.AVAILABLE, **ITEM_FIELDS
        )
        self.client.force_login(user)
        resp = self.client.get(reverse("items:detail", args=[item.id]))
        self.assertContains(resp, "QQ 12345")

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
