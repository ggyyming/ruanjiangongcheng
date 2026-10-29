"""校内认证服务测试（CP-R-05/06/07、CP-D-01/02）。"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import IdentityApplication
from .services import is_verified

User = get_user_model()


def make_user(name="张三"):
    return User.objects.create_user(username=f"u{name}", password="x123456")


class IsVerifiedTest(TestCase):
    def test_no_application_is_not_verified(self):
        user = make_user()
        self.assertFalse(is_verified(user_id=user.id))

    def test_pending_is_not_verified(self):
        user = make_user()
        IdentityApplication.objects.create(
            user=user, name="张三", staff_no="20240001", department="计算机学院"
        )
        self.assertFalse(is_verified(user_id=user.id))

    def test_approved_is_verified(self):
        user = make_user()
        app = IdentityApplication.objects.create(
            user=user, name="张三", staff_no="20240001", department="计算机学院"
        )
        app.status = IdentityApplication.Status.APPROVED
        app.save()
        self.assertTrue(is_verified(user_id=user.id))

    def test_rejected_is_not_verified(self):
        user = make_user()
        app = IdentityApplication.objects.create(
            user=user, name="张三", staff_no="20240001", department="计算机学院"
        )
        app.status = IdentityApplication.Status.REJECTED
        app.save()
        self.assertFalse(is_verified(user_id=user.id))

    def test_resubmit_keeps_history_and_rechecks(self):
        """CP-D-02：驳回后可重新提交，每次重新审核，保留历次结果。"""
        user = make_user()
        first = IdentityApplication.objects.create(
            user=user, name="张三", staff_no="20240001", department="计算机学院"
        )
        first.status = IdentityApplication.Status.REJECTED
        first.save()
        second = IdentityApplication.objects.create(
            user=user, name="张三", staff_no="20240001", department="计算机科学与技术学院"
        )
        second.status = IdentityApplication.Status.APPROVED
        second.save()
        self.assertEqual(user.identity_applications.count(), 2)  # 历史保留
        self.assertTrue(is_verified(user_id=user.id))  # 以最新一条为准

    def test_revoked_is_not_verified(self):
        """CP-D-04：认证撤销后不再具备校内认证资格。"""
        user = make_user()
        app = IdentityApplication.objects.create(
            user=user, name="张三", staff_no="20240001", department="计算机学院"
        )
        app.status = IdentityApplication.Status.REVOKED
        app.save()
        self.assertFalse(is_verified(user_id=user.id))
