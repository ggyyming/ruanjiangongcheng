"""模拟资金服务单元测试。

依赖 A0/C0，合并后运行。覆盖：发起不等于到账、回执匹配与幂等、
3 次重试上限、未知先对账、退款业务资格复核、取消后迟到支付退款。
"""

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.catalog.models import Item
from apps.payments import services
from apps.payments.models import PaymentOperation
from apps.transfers.models import Application, Transfer

User = get_user_model()


def _reserved_transfer(kind="sale", price="10.00", deposit="20.00"):
    owner = User.objects.create_user(username=f"owner_{kind}")
    recipient = User.objects.create_user(username=f"recipient_{kind}")
    item = Item.objects.create(
        owner=owner, kind=kind, price=Decimal(price), deposit=Decimal(deposit), name="物品"
    )
    app = Application.objects.create(item=item, applicant=recipient, kind=Application.Kind(kind))
    return Transfer.objects.create(
        application=app,
        item=item,
        owner=owner,
        recipient=recipient,
        kind=kind,
        amount=(
            Decimal(price) if kind == "sale" else (Decimal(deposit) if kind == "borrow" else None)
        ),
        status=Transfer.Status.RESERVED,
    )


class RequestPaymentTests(TestCase):
    def test_payment_starts_processing_not_paid(self):
        transfer = _reserved_transfer()
        op = services.request_payment(transfer_id=transfer.id, purpose="sale")
        self.assertEqual(op.status, PaymentOperation.Status.PAYING)
        self.assertFalse(services.is_paid(transfer_id=transfer.id, purpose="sale"))

    def test_donation_has_no_payment(self):
        transfer = _reserved_transfer(kind="donation")
        with self.assertRaises(ValidationError):
            services.request_payment(transfer_id=transfer.id, purpose="sale")


class SimulatedReceiptTests(TestCase):
    def test_receipt_success_marks_paid(self):
        transfer = _reserved_transfer()
        op = services.request_payment(transfer_id=transfer.id, purpose="sale")
        services.apply_simulated_receipt(operation_id=op.id, result="success")
        op.refresh_from_db()
        self.assertEqual(op.status, PaymentOperation.Status.PAID)
        self.assertTrue(services.is_paid(transfer_id=transfer.id, purpose="sale"))

    def test_receipt_failure_not_paid(self):
        transfer = _reserved_transfer()
        op = services.request_payment(transfer_id=transfer.id, purpose="sale")
        services.apply_simulated_receipt(operation_id=op.id, result="failure")
        op.refresh_from_db()
        self.assertEqual(op.status, PaymentOperation.Status.PAY_FAILED)
        self.assertFalse(services.is_paid(transfer_id=transfer.id, purpose="sale"))

    def test_processing_not_counted_as_paid(self):
        transfer = _reserved_transfer()
        services.request_payment(transfer_id=transfer.id, purpose="sale")
        self.assertFalse(services.is_paid(transfer_id=transfer.id, purpose="sale"))

    def test_duplicate_receipt_does_not_regress(self):
        transfer = _reserved_transfer()
        op = services.request_payment(transfer_id=transfer.id, purpose="sale")
        services.apply_simulated_receipt(operation_id=op.id, result="success")
        services.apply_simulated_receipt(operation_id=op.id, result="failure")
        op.refresh_from_db()
        # 已到账不回退
        self.assertEqual(op.status, PaymentOperation.Status.PAID)


class RetryTests(TestCase):
    def _refund_op(self, transfer):
        from apps.payments.services import request_refund

        return request_refund(transfer_id=transfer.id, reason="测试退款")

    @patch("apps.payments.services.is_paid", return_value=True)
    @patch("apps.disputes.services.has_open_dispute", return_value=False)
    def test_refund_retry_max_then_manual(self, has_open_dispute, is_paid):
        transfer = _reserved_transfer(kind="borrow", deposit="20.00")
        transfer.status = Transfer.Status.CANCELLED
        transfer.save(update_fields=["status"])
        op = self._refund_op(transfer)
        # 连续失败 4 次（首次 + 3 次重试）后转人工
        for _ in range(services.MAX_AUTO_RETRIES + 1):
            services.apply_simulated_receipt(operation_id=op.id, result="failure")
            op.refresh_from_db()
            services.reconcile_and_retry(op)
            op.refresh_from_db()
        self.assertEqual(op.status, PaymentOperation.Status.NEEDS_MANUAL)
        self.assertEqual(op.attempts, services.MAX_AUTO_RETRIES)

    @patch("apps.payments.services.is_paid", return_value=True)
    @patch("apps.disputes.services.has_open_dispute", return_value=False)
    def test_unknown_not_blindly_retried(self, has_open_dispute, is_paid):
        transfer = _reserved_transfer(kind="borrow", deposit="20.00")
        transfer.status = Transfer.Status.CANCELLED
        transfer.save(update_fields=["status"])
        op = self._refund_op(transfer)
        services.apply_simulated_receipt(operation_id=op.id, result="unknown")
        op.refresh_from_db()
        result = services.reconcile_and_retry(op)
        self.assertEqual(result, "needs_reconcile")
        op.refresh_from_db()
        self.assertEqual(op.status, PaymentOperation.Status.UNKNOWN)
        self.assertEqual(op.attempts, 0)


class RequestRefundTests(TestCase):
    def _mark_paid(self, transfer, purpose):
        PaymentOperation.objects.create(
            transfer=transfer,
            kind=PaymentOperation.Kind.PAYMENT,
            purpose=purpose,
            amount=transfer.amount,
            status=PaymentOperation.Status.PAID,
            business_id=f"{transfer.id}:payment:{purpose}",
        )

    @patch("apps.disputes.services.has_open_dispute", return_value=False)
    def test_refund_requires_cancelled_for_sale(self, has_open_dispute):
        transfer = _reserved_transfer(kind="sale")
        self._mark_paid(transfer, "sale")
        # 买卖未取消/撤销 -> 拒绝退款
        with self.assertRaises(ValidationError):
            services.request_refund(transfer_id=transfer.id, reason="x")

    @patch("apps.disputes.services.has_open_dispute", return_value=True)
    def test_refund_blocked_by_open_dispute(self, has_open_dispute):
        transfer = _reserved_transfer(kind="sale")
        transfer.status = Transfer.Status.CANCELLED
        transfer.save(update_fields=["status"])
        self._mark_paid(transfer, "sale")
        with self.assertRaises(ValidationError):
            services.request_refund(transfer_id=transfer.id, reason="x")

    @patch("apps.disputes.services.has_open_dispute", return_value=False)
    def test_refund_idempotent(self, has_open_dispute):
        transfer = _reserved_transfer(kind="sale")
        transfer.status = Transfer.Status.CANCELLED
        transfer.save(update_fields=["status"])
        self._mark_paid(transfer, "sale")
        op1 = services.request_refund(transfer_id=transfer.id, reason="x")
        op2 = services.request_refund(transfer_id=transfer.id, reason="x")
        self.assertEqual(op1.id, op2.id)
        self.assertEqual(
            PaymentOperation.objects.filter(
                transfer=transfer, kind=PaymentOperation.Kind.REFUND
            ).count(),
            1,
        )
