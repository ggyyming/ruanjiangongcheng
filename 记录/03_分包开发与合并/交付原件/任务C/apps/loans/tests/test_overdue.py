from django.test import TestCase

from apps.loans import services
from apps.loans.models import (
    BorrowAgreement,
    BorrowRestriction,
    Dispute,
    Notification,
)
from apps.loans.signals import borrow_applications_should_close

from .factories import agree_due_and_start, make_agreement, make_overdue, make_user


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, sender, **kwargs):
        self.calls.append(kwargs)


class OverdueTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner")
        self.borrower = make_user("borrower")
        self.first = agree_due_and_start(
            make_agreement(self.owner, self.borrower, item_title="相机")
        )
        self.second = agree_due_and_start(
            make_agreement(self.owner, self.borrower, item_title="投影仪")
        )
        make_overdue(self.first)
        make_overdue(self.second)

    def _return(self, agreement):
        services.confirm_return(agreement, self.borrower)
        services.confirm_return(agreement, self.owner)
        agreement.refresh_from_db()

    def test_scan_marks_overdue_restricts_and_notifies(self):
        self.first.refresh_from_db()
        self.second.refresh_from_db()
        self.assertIsNotNone(self.first.overdue_marked_at)
        self.assertIsNotNone(self.second.overdue_marked_at)
        self.assertTrue(services.is_borrow_restricted(self.borrower))
        self.assertEqual(
            Notification.objects.filter(recipient=self.borrower, event="loan.overdue").count(), 2
        )
        self.assertEqual(
            Notification.objects.filter(recipient=self.owner, event="loan.overdue").count(), 2
        )

    def test_scan_is_idempotent(self):
        self.assertEqual(services.scan_overdue(), 0)
        self.assertEqual(
            BorrowRestriction.objects.filter(
                user=self.borrower, cause=BorrowRestriction.CAUSE_OVERDUE, active=True
            ).count(),
            1,
        )

    def test_scan_notifies_flow_package_to_close_unselected_applications(self):
        recorder = Recorder()
        borrow_applications_should_close.connect(recorder, weak=False)
        self.addCleanup(borrow_applications_should_close.disconnect, recorder)

        third = agree_due_and_start(make_agreement(self.owner, self.borrower, item_title="帐篷"))
        make_overdue(third)

        self.assertEqual(len(recorder.calls), 1)
        self.assertEqual(recorder.calls[0]["user"], self.borrower)
        self.assertIn("逾期", recorder.calls[0]["reason"])

    def test_one_finished_loan_does_not_release(self):
        self._return(self.first)
        self.assertTrue(services.is_borrow_restricted(self.borrower))

        self._return(self.second)
        self.assertFalse(services.is_borrow_restricted(self.borrower))
        restriction = BorrowRestriction.objects.get(user=self.borrower)
        self.assertFalse(restriction.active)
        self.assertIsNotNone(restriction.released_at)
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.borrower, event="loan.restriction_released"
            ).exists()
        )

    def test_open_dispute_blocks_release_until_closed_and_loan_ended(self):
        self._return(self.first)
        dispute = services.open_dispute(
            self.second, self.borrower, Dispute.Kind.DAMAGE, "屏幕有裂纹"
        )
        services.record_plan(dispute, self.owner, "借用者自行维修，不涉及退款")
        services.confirm_plan_performed(dispute, self.owner)
        services.confirm_plan_performed(dispute, self.borrower)
        services.agree_dispute_end(dispute, self.owner)

        self.assertTrue(services.is_borrow_restricted(self.borrower))

        services.agree_dispute_end(dispute, self.borrower)
        self.second.refresh_from_db()
        dispute.refresh_from_db()
        self.assertEqual(dispute.status, Dispute.Status.CLOSED)
        self.assertEqual(self.second.status, BorrowAgreement.Status.ACTIVE)
        self.assertTrue(services.is_borrow_restricted(self.borrower))

        self._return(self.second)
        self.assertFalse(services.is_borrow_restricted(self.borrower))

    def test_loss_compensation_counts_as_valid_end(self):
        self._return(self.first)
        dispute = services.open_dispute(
            self.second, self.borrower, Dispute.Kind.LOSS, "物品在宿舍丢失"
        )
        services.record_plan(dispute, self.borrower, "按约定金额赔偿")
        services.confirm_plan_performed(dispute, self.owner)
        services.confirm_plan_performed(dispute, self.borrower)
        services.agree_dispute_end(dispute, self.owner)
        services.agree_dispute_end(dispute, self.borrower)

        self.second.refresh_from_db()
        dispute.refresh_from_db()
        self.assertEqual(dispute.status, Dispute.Status.CLOSED)
        self.assertEqual(self.second.status, BorrowAgreement.Status.COMPENSATED)
        self.assertFalse(services.is_borrow_restricted(self.borrower))

    def test_release_does_not_touch_other_restriction_causes(self):
        other = BorrowRestriction.objects.create(
            user=self.borrower, cause="admin", reason="管理员限制", active=True
        )
        self._return(self.first)
        self._return(self.second)

        other.refresh_from_db()
        self.assertTrue(other.active)
        self.assertFalse(services.is_borrow_restricted(self.borrower))
