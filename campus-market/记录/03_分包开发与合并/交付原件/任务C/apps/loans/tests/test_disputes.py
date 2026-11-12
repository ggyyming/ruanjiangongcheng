from django.core.exceptions import PermissionDenied
from django.test import TestCase

from apps.loans import services
from apps.loans.models import BorrowAgreement, Dispute, DisputeEvent
from apps.loans.services import LoanError
from apps.loans.signals import borrow_ended, deposit_refund_requested

from .factories import agree_due_and_start, make_agreement, make_user


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, sender, **kwargs):
        self.calls.append(kwargs)


class DisputeTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner")
        self.borrower = make_user("borrower")
        self.outsider = make_user("outsider")
        self.admin = make_user("admin", is_staff=True)
        self.other_admin = make_user("other-admin", is_staff=True)
        self.agreement = agree_due_and_start(make_agreement(self.owner, self.borrower))
        self.refunds = Recorder()
        self.ended = Recorder()
        deposit_refund_requested.connect(self.refunds, weak=False)
        borrow_ended.connect(self.ended, weak=False)
        self.addCleanup(deposit_refund_requested.disconnect, self.refunds)
        self.addCleanup(borrow_ended.disconnect, self.ended)

    def _settle(self, dispute, plan="按约定赔偿"):
        services.record_plan(dispute, self.borrower, plan)
        services.confirm_plan_performed(dispute, self.owner)
        services.confirm_plan_performed(dispute, self.borrower)
        services.agree_dispute_end(dispute, self.owner)
        services.agree_dispute_end(dispute, self.borrower)

    def test_damage_dispute_blocks_return_until_closed(self):
        dispute = services.open_dispute(
            self.agreement, self.borrower, Dispute.Kind.DAMAGE, "镜头有划痕"
        )
        self.agreement.refresh_from_db()
        self.assertEqual(self.agreement.status, BorrowAgreement.Status.DISPUTED)
        self.assertEqual(dispute.status, Dispute.Status.OPEN)

        with self.assertRaises(LoanError):
            services.confirm_return(self.agreement, self.borrower)

        self._settle(dispute)
        self.agreement.refresh_from_db()
        self.assertEqual(self.agreement.status, BorrowAgreement.Status.ACTIVE)
        self.assertEqual(self.refunds.calls, [])

        services.confirm_return(self.agreement, self.borrower)
        services.confirm_return(self.agreement, self.owner)
        self.agreement.refresh_from_db()
        self.assertEqual(self.agreement.status, BorrowAgreement.Status.RETURNED)
        self.assertEqual(len(self.refunds.calls), 1)
        self.assertEqual(self.refunds.calls[0]["reason"], "normal_return")

    def test_loss_settles_as_compensated_not_returned(self):
        dispute = services.open_dispute(
            self.agreement, self.borrower, Dispute.Kind.LOSS, "物品遗失"
        )
        services.record_plan(dispute, self.borrower, "赔偿 300 元")
        services.confirm_plan_performed(dispute, self.owner)
        services.confirm_plan_performed(dispute, self.borrower)
        services.agree_dispute_end(dispute, self.owner)
        services.agree_dispute_end(dispute, self.borrower)

        self.agreement.refresh_from_db()
        dispute.refresh_from_db()
        self.assertEqual(dispute.status, Dispute.Status.CLOSED)
        self.assertEqual(self.agreement.status, BorrowAgreement.Status.COMPENSATED)
        self.assertIsNotNone(self.agreement.compensated_at)
        self.assertIsNone(self.agreement.completed_at)
        self.assertEqual(self.ended.calls[-1]["outcome"], "compensated")
        self.assertEqual(self.refunds.calls[-1]["reason"], "loss_compensated")
        with self.assertRaises(LoanError):
            services.confirm_return(self.agreement, self.borrower)

    def test_damage_dispute_from_awaiting_return_restores_waiting_state(self):
        services.confirm_return(self.agreement, self.borrower)
        dispute = services.open_dispute(
            self.agreement, self.owner, Dispute.Kind.DAMAGE, "归还时发现损坏"
        )
        self._settle(dispute, plan="借用者赔付维修费，双方线下结清")
        self.agreement.refresh_from_db()
        self.assertEqual(self.agreement.status, BorrowAgreement.Status.AWAITING_RETURN)

        services.confirm_return(self.agreement, self.owner)
        self.agreement.refresh_from_db()
        self.assertEqual(self.agreement.status, BorrowAgreement.Status.RETURNED)

    def test_one_sided_end_agreement_does_not_close(self):
        dispute = services.open_dispute(
            self.agreement, self.borrower, Dispute.Kind.DAMAGE, "外壳破损"
        )
        services.record_plan(dispute, self.borrower, "赔偿 50 元")
        services.confirm_plan_performed(dispute, self.owner)
        services.confirm_plan_performed(dispute, self.borrower)
        services.agree_dispute_end(dispute, self.owner)
        dispute.refresh_from_db()
        self.assertEqual(dispute.status, Dispute.Status.OPEN)

        services.agree_dispute_end(dispute, self.borrower)
        dispute.refresh_from_db()
        self.assertEqual(dispute.status, Dispute.Status.CLOSED)

    def test_admin_cannot_close_before_both_performed(self):
        dispute = services.open_dispute(
            self.agreement, self.borrower, Dispute.Kind.DAMAGE, "边框凹痕"
        )
        services.record_plan(dispute, self.borrower, "赔偿 30 元")
        with self.assertRaises(LoanError):
            services.admin_close_dispute(dispute, self.admin, "管理员裁定")

    def test_admin_can_close_after_performance_when_opinions_differ(self):
        dispute = services.open_dispute(
            self.agreement, self.borrower, Dispute.Kind.DAMAGE, "屏幕碎裂"
        )
        services.record_plan(dispute, self.borrower, "赔偿 200 元")
        services.confirm_plan_performed(dispute, self.owner)
        services.confirm_plan_performed(dispute, self.borrower)
        services.agree_dispute_end(dispute, self.owner)

        services.admin_close_dispute(dispute, self.admin, "双方已履行，按方案结案")
        dispute.refresh_from_db()
        self.assertEqual(dispute.status, Dispute.Status.CLOSED)
        self.assertEqual(dispute.closed_by, self.admin)
        self.assertIn("结案", dispute.resolution)
        self.assertTrue(
            DisputeEvent.objects.filter(dispute=dispute, action="admin_closed").exists()
        )

    def test_claim_isolates_dispute_from_other_admins(self):
        dispute = services.open_dispute(
            self.agreement, self.borrower, Dispute.Kind.DAMAGE, "镜片脱胶"
        )
        self.assertTrue(dispute.can_view(self.other_admin))
        services.claim_dispute(dispute, self.admin)
        dispute.refresh_from_db()
        self.assertEqual(dispute.assigned_admin, self.admin)
        self.assertTrue(dispute.can_view(self.admin))
        self.assertFalse(dispute.can_view(self.other_admin))
        self.assertFalse(dispute.can_view(self.outsider))
        self.assertTrue(dispute.can_view(self.owner))
        with self.assertRaises(PermissionDenied):
            services.claim_dispute(dispute, self.other_admin)

    def test_repeated_confirmations_are_idempotent(self):
        dispute = services.open_dispute(
            self.agreement, self.borrower, Dispute.Kind.DAMAGE, "背带断裂"
        )
        services.record_plan(dispute, self.borrower, "借用者更换背带")
        services.confirm_plan_performed(dispute, self.borrower)
        services.confirm_plan_performed(dispute, self.borrower)
        self.assertEqual(
            DisputeEvent.objects.filter(dispute=dispute, action="performed_confirmed").count(), 1
        )

    def test_non_party_cannot_open_or_plan(self):
        with self.assertRaises(PermissionDenied):
            services.open_dispute(self.agreement, self.outsider, Dispute.Kind.DAMAGE, "无关用户")
        dispute = services.open_dispute(
            self.agreement, self.borrower, Dispute.Kind.DAMAGE, "真实损坏"
        )
        with self.assertRaises(PermissionDenied):
            services.record_plan(dispute, self.outsider, "无关方案")
