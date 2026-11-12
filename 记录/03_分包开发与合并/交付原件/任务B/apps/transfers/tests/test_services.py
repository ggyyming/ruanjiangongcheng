"""流转服务单元测试。

依赖 A0 的 apps.catalog.Item 模型与 A/C 服务，故本文件在 A0/C0 合并后运行。
A/C 服务函数在函数体内导入，这里在真实模块路径打桩以隔离验证 B 自身逻辑。

假定 A 的 Item 字段：owner(物主)、kind(sale/donation/borrow)、price(售价)、
deposit(借用押金展示)、name。字段名与 A0 实际对齐后如需调整只改 ``_item``。
"""

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from apps.catalog.models import Item
from apps.transfers import services
from apps.transfers.models import Application, Revocation, Transfer

User = get_user_model()


def _item(owner, kind="sale", price="10.00", deposit="20.00"):
    return Item.objects.create(
        owner=owner,
        kind=kind,
        price=Decimal(price),
        deposit=Decimal(deposit),
        name="测试物品",
    )


class ApplyTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner")
        self.buyer = User.objects.create_user(username="buyer")
        self.item = _item(self.owner)

    @patch("apps.accounts.services.is_verified", return_value=True)
    @patch("apps.catalog.services.can_display", return_value=True)
    def test_apply_creates_pending_application(self, can_display, is_verified):
        app = services.apply(actor=self.buyer, item_id=self.item.id)
        self.assertEqual(app.status, Application.Status.PENDING)
        self.assertEqual(app.kind, Application.Kind.SALE)

    @patch("apps.accounts.services.is_verified", return_value=False)
    def test_unverified_apply_rejected(self, is_verified):
        with self.assertRaises(PermissionDenied):
            services.apply(actor=self.buyer, item_id=self.item.id)
        self.assertEqual(Application.objects.count(), 0)

    @patch("apps.accounts.services.is_verified", return_value=True)
    @patch("apps.catalog.services.can_display", return_value=True)
    def test_apply_own_item_rejected(self, can_display, is_verified):
        with self.assertRaises(ValidationError):
            services.apply(actor=self.owner, item_id=self.item.id)

    @patch("apps.accounts.services.is_verified", return_value=True)
    @patch("apps.catalog.services.can_display", return_value=True)
    def test_duplicate_pending_apply_rejected(self, can_display, is_verified):
        services.apply(actor=self.buyer, item_id=self.item.id)
        with self.assertRaises(ValidationError):
            services.apply(actor=self.buyer, item_id=self.item.id)


class ReserveTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner")
        self.buyer = User.objects.create_user(username="buyer")
        self.other = User.objects.create_user(username="other")
        self.item = _item(self.owner, kind="sale", price="10.00")
        self.app1 = Application.objects.create(
            item=self.item, applicant=self.buyer, kind=Application.Kind.SALE
        )
        self.app2 = Application.objects.create(
            item=self.item, applicant=self.other, kind=Application.Kind.SALE
        )

    @patch("apps.catalog.services.change_availability", return_value=None)
    def test_reserve_selects_one_and_closes_others(self, change_availability):
        transfer = services.reserve(actor=self.owner, application_id=self.app1.id)
        self.app1.refresh_from_db()
        self.app2.refresh_from_db()
        self.assertEqual(self.app1.status, Application.Status.SELECTED)
        self.assertEqual(self.app2.status, Application.Status.CLOSED)
        self.assertEqual(transfer.status, Transfer.Status.RESERVED)
        self.assertEqual(transfer.amount, Decimal("10.00"))

    def test_non_owner_cannot_reserve(self):
        with self.assertRaises(PermissionDenied):
            services.reserve(actor=self.buyer, application_id=self.app1.id)

    @patch("apps.catalog.services.change_availability", return_value=None)
    def test_reserve_already_handled_rejected(self, change_availability):
        services.reserve(actor=self.owner, application_id=self.app1.id)
        with self.assertRaises(ValidationError):
            services.reserve(actor=self.owner, application_id=self.app1.id)

    @patch("apps.catalog.services.change_availability", return_value=None)
    def test_reserve_twice_on_same_item_rejected(self, change_availability):
        services.reserve(actor=self.owner, application_id=self.app1.id)
        # app2 已被关闭，再次 reserve 会因状态不符失败
        with self.assertRaises(ValidationError):
            services.reserve(actor=self.owner, application_id=self.app2.id)

    def test_unique_active_transfer_per_item(self):
        # 同一物品同时最多一笔进行中流转：数据库唯一约束兜底并发
        Transfer.objects.create(
            application=self.app1,
            item=self.item,
            owner=self.owner,
            recipient=self.buyer,
            kind=Transfer.Kind.SALE,
            status=Transfer.Status.RESERVED,
        )
        with self.assertRaises(IntegrityError):
            Transfer.objects.create(
                application=self.app2,
                item=self.item,
                owner=self.owner,
                recipient=self.other,
                kind=Transfer.Kind.SALE,
                status=Transfer.Status.RESERVED,
            )


class ConfirmDeliveryTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner")
        self.buyer = User.objects.create_user(username="buyer")
        self.item = _item(self.owner, kind="sale", price="10.00")
        self.app = Application.objects.create(
            item=self.item, applicant=self.buyer, kind=Application.Kind.SALE
        )
        with patch("apps.catalog.services.change_availability"):
            self.transfer = services.reserve(actor=self.owner, application_id=self.app.id)

    def _mark_paid(self):
        from apps.payments.models import PaymentOperation

        PaymentOperation.objects.create(
            transfer=self.transfer,
            kind=PaymentOperation.Kind.PAYMENT,
            purpose=PaymentOperation.Purpose.SALE,
            amount=Decimal("10.00"),
            status=PaymentOperation.Status.PAID,
            business_id=f"{self.transfer.id}:payment:sale",
        )

    @patch("apps.payments.services.initiate_settlement", return_value=None)
    def test_sale_confirm_requires_payment(self, initiate_settlement):
        with self.assertRaises(ValidationError):
            services.confirm_delivery(actor=self.owner, transfer_id=self.transfer.id)

    @patch("apps.payments.services.initiate_settlement", return_value=None)
    def test_single_confirmation_does_not_complete(self, initiate_settlement):
        self._mark_paid()
        services.confirm_delivery(actor=self.owner, transfer_id=self.transfer.id)
        self.transfer.refresh_from_db()
        self.assertIsNotNone(self.transfer.owner_confirmed_at)
        self.assertIsNone(self.transfer.recipient_confirmed_at)
        self.assertEqual(self.transfer.status, Transfer.Status.RESERVED)
        self.assertFalse(initiate_settlement.called)

    @patch("apps.payments.services.initiate_settlement", return_value=None)
    def test_both_confirm_completes_and_settles(self, initiate_settlement):
        self._mark_paid()
        services.confirm_delivery(actor=self.owner, transfer_id=self.transfer.id)
        services.confirm_delivery(actor=self.buyer, transfer_id=self.transfer.id)
        self.transfer.refresh_from_db()
        self.assertEqual(self.transfer.status, Transfer.Status.COMPLETED)
        initiate_settlement.assert_called_once_with(transfer_id=self.transfer.id)

    @patch("apps.payments.services.initiate_settlement", return_value=None)
    def test_cannot_confirm_for_other_party(self, initiate_settlement):
        self._mark_paid()
        outsider = User.objects.create_user(username="outsider")
        with self.assertRaises(PermissionDenied):
            services.confirm_delivery(actor=outsider, transfer_id=self.transfer.id)

    @patch("apps.payments.services.initiate_settlement", return_value=None)
    def test_repeat_confirm_idempotent(self, initiate_settlement):
        self._mark_paid()
        services.confirm_delivery(actor=self.owner, transfer_id=self.transfer.id)
        first = self.transfer.owner_confirmed_at
        services.confirm_delivery(actor=self.owner, transfer_id=self.transfer.id)
        self.transfer.refresh_from_db()
        self.assertEqual(self.transfer.owner_confirmed_at, first)


class CancelTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner")
        self.buyer = User.objects.create_user(username="buyer")
        self.item = _item(self.owner, kind="sale", price="10.00")
        self.app = Application.objects.create(
            item=self.item, applicant=self.buyer, kind=Application.Kind.SALE
        )
        with patch("apps.catalog.services.change_availability"):
            self.transfer = services.reserve(actor=self.owner, application_id=self.app.id)

    @patch("apps.catalog.services.change_availability", return_value=None)
    def test_cancel_before_delivery(self, change_availability):
        services.cancel_before_delivery(
            actor=self.owner, transfer_id=self.transfer.id, reason="不想卖了"
        )
        self.transfer.refresh_from_db()
        self.app.refresh_from_db()
        self.assertEqual(self.transfer.status, Transfer.Status.CANCELLED)
        self.assertEqual(self.app.status, Application.Status.CANCELLED)

    def test_cancel_requires_reason(self):
        with self.assertRaises(ValidationError):
            services.cancel_before_delivery(
                actor=self.owner, transfer_id=self.transfer.id, reason=""
            )

    @patch("apps.payments.services.is_paid", return_value=True)
    def test_cancel_after_one_confirmed_rejected(self, is_paid):
        # 一方已确认 -> 不能单方取消
        self.transfer.owner_confirmed_at = timezone.now()
        self.transfer.save(update_fields=["owner_confirmed_at"])
        with self.assertRaises(ValidationError):
            services.cancel_before_delivery(
                actor=self.buyer, transfer_id=self.transfer.id, reason="想取消"
            )


class RevokeTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner")
        self.buyer = User.objects.create_user(username="buyer")
        self.item = _item(self.owner, kind="sale", price="10.00")
        self.app = Application.objects.create(
            item=self.item, applicant=self.buyer, kind=Application.Kind.SALE
        )
        with patch("apps.catalog.services.change_availability"):
            self.transfer = services.reserve(actor=self.owner, application_id=self.app.id)

    def _mark_owner_confirmed(self):
        self.transfer.owner_confirmed_at = timezone.now()
        self.transfer.save(update_fields=["owner_confirmed_at"])

    def test_start_revoke_requires_one_confirmation(self):
        with self.assertRaises(ValidationError):
            services.start_revoke(actor=self.buyer, transfer_id=self.transfer.id, reason="想撤销")

    def test_start_revoke_after_one_confirmed(self):
        self._mark_owner_confirmed()
        revocation = services.start_revoke(
            actor=self.buyer, transfer_id=self.transfer.id, reason="想撤销"
        )
        self.transfer.refresh_from_db()
        self.assertEqual(self.transfer.revoke_status, Transfer.RevokeStatus.NEGOTIATING)
        self.assertEqual(revocation.initiator, Revocation.Side.RECIPIENT)
        self.assertIsNotNone(revocation.recipient_agreed_at)

    @patch("apps.catalog.services.change_availability", return_value=None)
    def test_revoke_completes_when_both_declare_and_agree(self, change_availability):
        self._mark_owner_confirmed()
        services.start_revoke(actor=self.buyer, transfer_id=self.transfer.id, reason="想撤销")
        services.declare_direction(
            actor=self.buyer, transfer_id=self.transfer.id, direction="not_handed_over"
        )
        services.agree_revoke(actor=self.owner, transfer_id=self.transfer.id)
        services.declare_direction(
            actor=self.owner, transfer_id=self.transfer.id, direction="not_handed_over"
        )
        self.transfer.refresh_from_db()
        self.assertEqual(self.transfer.status, Transfer.Status.REVOKED)
        self.assertEqual(self.transfer.revoke_status, Transfer.RevokeStatus.REVOKED)
        change_availability.assert_called_once()

    def test_revoke_withdraw_restores(self):
        self._mark_owner_confirmed()
        services.start_revoke(actor=self.buyer, transfer_id=self.transfer.id, reason="想撤销")
        services.withdraw_revoke(actor=self.buyer, transfer_id=self.transfer.id)
        services.withdraw_revoke(actor=self.owner, transfer_id=self.transfer.id)
        self.transfer.refresh_from_db()
        self.assertEqual(self.transfer.revoke_status, Transfer.RevokeStatus.NONE)
        self.assertEqual(self.transfer.status, Transfer.Status.RESERVED)
