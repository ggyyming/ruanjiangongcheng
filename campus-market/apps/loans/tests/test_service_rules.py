"""C 部分（借用/归还/延期/逾期/争议）服务层单元测试补充（精简版，18 例）。

本文件直接调用 ``apps.loans.services`` 的函数，断言返回值、异常类型和数据库状态，
聚焦现有测试未覆盖的高价值业务规则分支：押金金额校验、陈旧令牌、权限与状态机边界。
对应的用例说明与测试脚本见 ``tests/test_record/``。
"""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.utils import timezone

from apps.loans import services
from apps.loans.models import BorrowAgreement, Dispute, ExtensionRequest
from apps.loans.services import LoanError
from apps.payments.services import apply_simulated_receipt, pay_transfer

from .factories import agree_due_and_start, make_agreement, make_user


class TermsRulesTests(TestCase):
    """借用约定：归还时间与押金金额的校验、锁定与幂等（CP-R-14 / CP-R-21 / CP-ST-09）。"""

    def setUp(self):
        self.owner = make_user("terms_owner")
        self.borrower = make_user("terms_borrower")
        self.agreement = make_agreement(self.owner, self.borrower)

    def test_set_due_date_rejects_past_due(self):
        with self.assertRaises(LoanError):
            services.set_due_date(self.agreement, self.owner, timezone.now() - timedelta(minutes=1))

    def test_set_due_date_rejects_invalid_deposit(self):
        invalid_amounts = [
            100.0,  # 非 Decimal
            Decimal("0"),  # 不大于零
            Decimal("100000000"),  # 达到一亿元上限
            Decimal("100.005"),  # 超过两位小数
        ]
        due = timezone.now() + timedelta(days=1)
        for amount in invalid_amounts:
            with self.subTest(deposit=amount):
                with self.assertRaises(LoanError):
                    services.set_due_date(self.agreement, self.owner, due, deposit_amount=amount)

    def test_set_due_date_rejects_deposit_change_after_payment(self):
        due = timezone.now() + timedelta(days=2)
        services.set_due_date(self.agreement, self.owner, due)
        services.confirm_due_date(self.agreement, self.borrower)
        op = pay_transfer(actor=self.borrower, transfer_id=self.agreement.transfer_id)
        apply_simulated_receipt(operation_id=op.pk, result="success")

        with self.assertRaises(LoanError):
            services.set_due_date(self.agreement, self.owner, due, deposit_amount=Decimal("999.00"))

    def test_confirm_due_date_rejects_stale_terms_key(self):
        due = timezone.now() + timedelta(days=2)
        services.set_due_date(self.agreement, self.owner, due)
        self.agreement.refresh_from_db()
        with self.assertRaises(LoanError):
            services.confirm_due_date(self.agreement, self.borrower, terms_key="stale")


class DeliveryAndQueryTests(TestCase):
    """交付判断与查询 helper（delivery_ready / has_open_dispute）。"""

    def setUp(self):
        self.owner = make_user("query_owner")
        self.borrower = make_user("query_borrower")
        self.agreement = make_agreement(self.owner, self.borrower)

    def test_delivery_ready_requires_both_confirmations(self):
        self.assertFalse(services.delivery_ready(transfer_id=self.agreement.transfer_id))

        due = timezone.now() + timedelta(days=2)
        services.set_due_date(self.agreement, self.owner, due)
        self.assertFalse(services.delivery_ready(transfer_id=self.agreement.transfer_id))

        services.confirm_due_date(self.agreement, self.borrower)
        self.assertTrue(services.delivery_ready(transfer_id=self.agreement.transfer_id))

    def test_has_open_dispute_detects_open_and_closed(self):
        agree_due_and_start(self.agreement)
        dispute = services.open_dispute(self.agreement, self.owner, Dispute.Kind.DAMAGE, "屏幕破裂")
        self.assertTrue(services.has_open_dispute(transfer_id=self.agreement.transfer_id))

        Dispute.objects.filter(pk=dispute.pk).update(status=Dispute.Status.CLOSED)
        self.assertFalse(services.has_open_dispute(transfer_id=self.agreement.transfer_id))


class ExtensionRulesTests(TestCase):
    """归还期限延期规则（CP-R-18 / CP-D-07 / CP-D-19）。"""

    def setUp(self):
        self.owner = make_user("ext_owner")
        self.borrower = make_user("ext_borrower")
        self.outsider = make_user("ext_outsider")
        self.agreement = agree_due_and_start(make_agreement(self.owner, self.borrower))

    def test_request_extension_outsider_denied(self):
        with self.assertRaises(PermissionDenied):
            services.request_extension(
                self.agreement, self.outsider, self.agreement.due_at + timedelta(days=1)
            )

    def test_request_extension_requires_active(self):
        pending = make_agreement(self.owner, self.borrower, item_title="笔记本")
        with self.assertRaises(LoanError):
            services.request_extension(pending, self.borrower, timezone.now() + timedelta(days=3))

    def test_decide_extension_approve_rejects_past_proposed(self):
        extension = services.request_extension(
            self.agreement, self.borrower, self.agreement.due_at + timedelta(days=1)
        )
        ExtensionRequest.objects.filter(pk=extension.pk).update(
            proposed_due_at=timezone.now() - timedelta(minutes=1)
        )

        with self.assertRaises(LoanError):
            services.decide_extension(extension, self.owner, approve=True)


class DisputePlanRulesTests(TestCase):
    """争议开启、方案记录与履行确认的规则（CP-R-26 / CP-D-12 / CP-ST-29）。"""

    def setUp(self):
        self.owner = make_user("plan_owner")
        self.borrower = make_user("plan_borrower")
        self.agreement = agree_due_and_start(make_agreement(self.owner, self.borrower))

    def _open_damage(self):
        return services.open_dispute(self.agreement, self.owner, Dispute.Kind.DAMAGE, "屏幕破裂")

    def test_open_dispute_rejects_duplicate(self):
        self._open_damage()
        with self.assertRaises(LoanError):
            services.open_dispute(self.agreement, self.borrower, Dispute.Kind.DAMAGE, "再次提交")

    def test_open_dispute_rejects_loss_from_awaiting_return(self):
        services.confirm_return(self.agreement, self.borrower)
        self.agreement.refresh_from_db()
        with self.assertRaises(LoanError):
            services.open_dispute(self.agreement, self.owner, Dispute.Kind.LOSS, "丢失")

    def test_record_plan_change_resets_confirmations(self):
        dispute = self._open_damage()
        services.record_plan(dispute, self.owner, "方案A")
        services.confirm_plan_performed(dispute, self.owner)
        dispute.refresh_from_db()
        self.assertIsNotNone(dispute.owner_performed_at)

        services.record_plan(dispute, self.owner, "方案B")
        dispute.refresh_from_db()
        self.assertIsNone(dispute.owner_performed_at)

    def test_confirm_performed_rejects_stale_plan_key(self):
        dispute = self._open_damage()
        services.record_plan(dispute, self.owner, "方案A")
        with self.assertRaises(LoanError):
            services.confirm_plan_performed(dispute, self.owner, plan_key="stale")


class DisputeAdminPermissionTests(TestCase):
    """争议管理员权限：认领与关闭（CP-D-12 / CP-D-22）。"""

    def setUp(self):
        self.owner = make_user("admin_owner")
        self.borrower = make_user("admin_borrower")
        self.regular = make_user("admin_regular")
        self.admin = make_user("admin_one", is_staff=True)
        self.other_admin = make_user("admin_two", is_staff=True)
        self.agreement = agree_due_and_start(make_agreement(self.owner, self.borrower))
        self.dispute = services.open_dispute(
            self.agreement, self.owner, Dispute.Kind.DAMAGE, "屏幕破裂"
        )

    def test_claim_requires_staff(self):
        with self.assertRaises(PermissionDenied):
            services.claim_dispute(self.dispute, self.regular)

    def test_admin_close_rejects_other_admin(self):
        services.claim_dispute(self.dispute, self.admin)
        with self.assertRaises(PermissionDenied):
            services.admin_close_dispute(self.dispute, self.other_admin)


class OverdueAndRefundRulesTests(TestCase):
    """逾期扫描与退款的边界与幂等（CP-R-16 / CP-ST-31）。"""

    def setUp(self):
        self.owner = make_user("overdue_owner")
        self.borrower = make_user("overdue_borrower")

    def test_scan_marks_disputed(self):
        agreement = agree_due_and_start(make_agreement(self.owner, self.borrower))
        services.open_dispute(agreement, self.owner, Dispute.Kind.DAMAGE, "屏幕破裂")
        BorrowAgreement.objects.filter(pk=agreement.pk).update(
            due_at=timezone.now() - timedelta(hours=1)
        )

        marked = services.scan_overdue()

        self.assertEqual(marked, 1)

    def test_scan_excludes_pending_delivery(self):
        agreement = make_agreement(self.owner, self.borrower)
        BorrowAgreement.objects.filter(pk=agreement.pk).update(
            due_at=timezone.now() - timedelta(hours=1)
        )

        marked = services.scan_overdue()

        self.assertEqual(marked, 0)
        agreement.refresh_from_db()
        self.assertIsNone(agreement.overdue_marked_at)

    def test_request_deposit_refund_is_idempotent(self):
        agreement = agree_due_and_start(make_agreement(self.owner, self.borrower))
        services.confirm_return(agreement, self.borrower)
        agreement.refresh_from_db()
        services.confirm_return(agreement, agreement.owner)
        agreement.refresh_from_db()
        first_at = agreement.deposit_refund_requested_at
        self.assertIsNotNone(first_at)

        self.assertFalse(services.request_deposit_refund(agreement, "again"))
        agreement.refresh_from_db()
        self.assertEqual(agreement.deposit_refund_requested_at, first_at)
