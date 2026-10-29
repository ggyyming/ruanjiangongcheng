"""物品市场服务测试（CP-R-08、CP-D-03/05/10/11 及共同接口约定）。"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.accounts.models import IdentityApplication

from .models import Item
from .services import can_display, change_availability

User = get_user_model()


def make_item(owner, status=Item.DisplayStatus.AVAILABLE, **kwargs):
    defaults = dict(
        name="高等数学教材",
        category="教材",
        description="九成新",
        flow_type=Item.FlowType.SALE,
        price="15.00",
        owner_nickname="小张",
        campus_area="东区宿舍",
    )
    defaults.update(kwargs)
    return Item.objects.create(owner=owner, display_status=status, **defaults)


def approve(user):
    IdentityApplication.objects.create(
        user=user,
        name=user.username,
        staff_no="20240001",
        department="计算机学院",
        status=IdentityApplication.Status.APPROVED,
    )


class CanDisplayTest(TestCase):
    def test_available_and_verified_owner(self):
        user = User.objects.create_user(username="u1", password="x123456")
        approve(user)
        item = make_item(user)
        self.assertTrue(can_display(item_id=item.id))

    def test_pending_item_not_displayed(self):
        """CP-D-05：先审核后公开。"""
        user = User.objects.create_user(username="u1", password="x123456")
        approve(user)
        item = make_item(user, status=Item.DisplayStatus.PENDING)
        self.assertFalse(can_display(item_id=item.id))

    def test_rejected_item_not_displayed(self):
        user = User.objects.create_user(username="u1", password="x123456")
        approve(user)
        item = make_item(user, status=Item.DisplayStatus.REJECTED)
        self.assertFalse(can_display(item_id=item.id))

    def test_owner_revoked_not_displayed(self):
        """物主资格随认证撤销丧失，物品不可公开展示。"""
        user = User.objects.create_user(username="u1", password="x123456")
        IdentityApplication.objects.create(
            user=user,
            name=user.username,
            staff_no="20240001",
            department="计算机学院",
            status=IdentityApplication.Status.REVOKED,
        )
        item = make_item(user)
        self.assertFalse(can_display(item_id=item.id))

    def test_missing_item(self):
        self.assertFalse(can_display(item_id=99999))


class ChangeAvailabilityTest(TestCase):
    def test_offline_requires_reason(self):
        user = User.objects.create_user(username="u1", password="x123456")
        approve(user)
        item = make_item(user)
        with self.assertRaises(ValidationError):
            change_availability(item_id=item.id, available=False, reason="")

    def test_offline_sets_status_and_logs(self):
        user = User.objects.create_user(username="u1", password="x123456")
        approve(user)
        item = make_item(user)
        result = change_availability(item_id=item.id, available=False, reason="违规下架")
        item.refresh_from_db()
        self.assertEqual(result.display_status, Item.DisplayStatus.OFFLINE)
        self.assertEqual(item.availability_changes.count(), 1)
        self.assertFalse(can_display(item_id=item.id))

    def test_restore_requires_verified_owner(self):
        user = User.objects.create_user(username="u1", password="x123456")
        approve(user)
        item = make_item(user, status=Item.DisplayStatus.OFFLINE)
        result = change_availability(item_id=item.id, available=True, reason="重新上架")
        self.assertEqual(result.display_status, Item.DisplayStatus.AVAILABLE)

    def test_restore_rejected_when_owner_unverified(self):
        user = User.objects.create_user(username="u1", password="x123456")
        approve(user)
        item = make_item(user, status=Item.DisplayStatus.OFFLINE)
        IdentityApplication.objects.create(
            user=user,
            name=user.username,
            staff_no="20240001",
            department="计算机学院",
            status=IdentityApplication.Status.REVOKED,
        )
        with self.assertRaises(ValidationError):
            change_availability(item_id=item.id, available=True, reason="重新上架")

    def test_pending_cannot_skip_review(self):
        """available=True 仍校验公开条件：待审核物品不能直接恢复公开。"""
        user = User.objects.create_user(username="u1", password="x123456")
        approve(user)
        item = make_item(user, status=Item.DisplayStatus.PENDING)
        with self.assertRaises(ValidationError):
            change_availability(item_id=item.id, available=True, reason="跳过审核")

    def test_history_not_rewritten(self):
        """共同约定：变更只追加记录，不改写历史。"""
        user = User.objects.create_user(username="u1", password="x123456")
        approve(user)
        item = make_item(user)
        change_availability(item_id=item.id, available=False, reason="第一次下架")
        change_availability(item_id=item.id, available=True, reason="重新上架")
        change_availability(item_id=item.id, available=False, reason="第二次下架")
        self.assertEqual(item.availability_changes.count(), 3)
        reasons = list(item.availability_changes.values_list("reason", flat=True))
        self.assertEqual(reasons, ["第二次下架", "重新上架", "第一次下架"])
