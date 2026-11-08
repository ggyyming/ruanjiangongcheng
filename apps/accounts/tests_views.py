"""认证流程页面测试（CP-R-05/06/07、CP-D-01/02/22、CP-D-04）。"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Item

from .models import IdentityApplication
from .services import is_verified

User = get_user_model()


def make_user(username="u1", password="x123456", staff=False):
    return User.objects.create_user(username=username, password=password, is_staff=staff)


def make_verified_user():
    user = make_user()
    IdentityApplication.objects.create(
        user=user,
        name="张三",
        staff_no="20240001",
        department="计算机学院",
        status=IdentityApplication.Status.APPROVED,
    )
    return user


class RegisterLoginTest(TestCase):
    def test_register_then_login(self):
        resp = self.client.post(
            reverse("accounts:register"),
            {"username": "u1", "password1": "x123456aa", "password2": "x123456aa"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(User.objects.filter(username="u1").exists())

    def test_login_page_accessible(self):
        resp = self.client.get(reverse("accounts:login"))
        self.assertEqual(resp.status_code, 200)


class IdentityFlowTest(TestCase):
    def test_unverified_user_cannot_create_item_page(self):
        """CP-R-07：未认证不可发布，拒绝时不新增业务记录。"""
        user = make_user()
        self.client.force_login(user)
        resp = self.client.post(
            reverse("items:create"),
            {
                "name": "高等数学教材",
                "category": "教材",
                "description": "九成新",
                "flow_type": "出售",
                "price": "15.00",
                "owner_nickname": "小张",
                "campus_area": "东区宿舍",
            },
        )
        self.assertEqual(resp.status_code, 200)  # 返回表单页并提示错误
        self.assertEqual(Item.objects.count(), 0)

    def test_submit_review_reject_resubmit(self):
        """CP-D-02：驳回记录原因，可修改重提，每次重新审核，历次保留。"""
        user = make_user()
        self.client.force_login(user)
        self.client.post(
            reverse("accounts:identity_apply"),
            {"name": "张三", "staff_no": "20240001", "department": "计算机学院"},
        )
        app = IdentityApplication.objects.get()
        self.assertEqual(app.status, IdentityApplication.Status.PENDING)

        admin = make_user(username="admin", staff=True)
        self.client.force_login(admin)
        resp = self.client.post(
            reverse("accounts:review", args=[app.id]), {"reason": "院系信息有误"}
        )
        self.assertEqual(resp.status_code, 302)
        app.refresh_from_db()
        self.assertEqual(app.status, IdentityApplication.Status.REJECTED)
        self.assertEqual(app.review_reason, "院系信息有误")

        # 用户重新提交 → 新申请，重新审核
        self.client.force_login(user)
        self.client.post(
            reverse("accounts:identity_apply"),
            {"name": "张三", "staff_no": "20240001", "department": "计算机科学与技术学院"},
        )
        self.assertEqual(IdentityApplication.objects.count(), 2)
        self.assertFalse(is_verified(user_id=user.id))

        new_app = IdentityApplication.objects.filter(user=user).first()
        self.client.force_login(admin)
        self.client.post(reverse("accounts:review", args=[new_app.id]), {"approve": "on"})
        self.assertTrue(is_verified(user_id=user.id))

    def test_reject_without_reason_blocked(self):
        user = make_user()
        app = IdentityApplication.objects.create(
            user=user, name="张三", staff_no="20240001", department="计算机学院"
        )
        admin = make_user(username="admin", staff=True)
        self.client.force_login(admin)
        resp = self.client.post(reverse("accounts:review", args=[app.id]), {})
        app.refresh_from_db()
        self.assertEqual(app.status, IdentityApplication.Status.PENDING)
        self.assertContains(resp, "驳回时必须填写原因")

    def test_identity_detail_private_to_others(self):
        """CP-D-22：身份资料仅申请人及审核管理员可见。"""
        user = make_user()
        app = IdentityApplication.objects.create(
            user=user, name="张三", staff_no="20240001", department="计算机学院"
        )
        other = make_user(username="u2")
        self.client.force_login(other)
        resp = self.client.get(reverse("accounts:identity_detail", args=[app.id]))
        self.assertEqual(resp.status_code, 403)

    def test_staff_can_view_identity_detail(self):
        user = make_user()
        app = IdentityApplication.objects.create(
            user=user, name="张三", staff_no="20240001", department="计算机学院"
        )
        admin = make_user(username="admin", staff=True)
        self.client.force_login(admin)
        resp = self.client.get(reverse("accounts:identity_detail", args=[app.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "20240001")


class RevokeTest(TestCase):
    def test_revoke_downlists_public_items_and_unverifies(self):
        """CP-D-04：撤销后下架未预留公开物品，恢复须重新审核。"""
        user = make_verified_user()
        item = Item.objects.create(
            owner=user,
            name="高等数学教材",
            category="教材",
            description="九成新",
            flow_type=Item.FlowType.SALE,
            price="15.00",
            owner_nickname="小张",
            campus_area="东区宿舍",
            display_status=Item.DisplayStatus.AVAILABLE,
        )
        admin = make_user(username="admin", staff=True)
        self.client.force_login(admin)
        resp = self.client.post(reverse("accounts:revoke", args=[user.id]), {"reason": "违规"})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(is_verified(user_id=user.id))
        item.refresh_from_db()
        self.assertEqual(item.display_status, Item.DisplayStatus.OFFLINE)
        self.assertEqual(item.availability_changes.count(), 1)

    def test_revoke_requires_reason(self):
        user = make_verified_user()
        admin = make_user(username="admin", staff=True)
        self.client.force_login(admin)
        self.client.post(reverse("accounts:revoke", args=[user.id]), {"reason": ""})
        self.assertTrue(is_verified(user_id=user.id))
