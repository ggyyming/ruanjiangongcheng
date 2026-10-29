from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.utils import timezone

from apps.loans import services
from apps.loans.models import BorrowAgreement
from apps.loans.services import LoanError
from apps.loans.signals import borrow_ended, deposit_refund_requested

from .factories import agree_due_and_start, make_agreement, make_user


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, sender, **kwargs):
        self.calls.append(kwargs)


class BorrowFlowTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner")
        self.borrower = make_user("borrower")
        self.outsider = make_user("outsider")
        self.agreement = make_agreement(self.owner, self.borrower)
        self.refunds = Recorder()
        self.ended = Recorder()
        deposit_refund_requested.connect(self.refunds, weak=False)
        borrow_ended.connect(self.ended, weak=False)
        self.addCleanup(deposit_refund_requested.disconnect, self.refunds)
        self.addCleanup(borrow_ended.disconnect, self.ended)

    def test_start_requires_both_due_confirmations(self):
        due = timezone.now() + timedelta(days=2)
        services.set_due_date(self.agreement, self.owner, due)
        self.agreement.refresh_from_db()
        self.assertFalse(self.agreement.is_due_confirmed())

        with self.assertRaises(LoanError):
            services.start_borrow(self.agreement)

        services.confirm_due_date(self.agreement, self.borrower)
        services.start_borrow(self.agreement)
        self.agreement.refresh_from_db()
        self.assertEqual(self.agreement.status, BorrowAgreement.Status.ACTIVE)
        self.assertIsNotNone(self.agreement.started_at)

    def test_new_due_time_resets_other_side_confirmation(self):
        first = timezone.now() + timedelta(days=2)
        second = timezone.now() + timedelta(days=3)
        services.set_due_date(self.agreement, self.owner, first)
        services.confirm_due_date(self.agreement, self.borrower)
        self.agreement.refresh_from_db()
        self.assertTrue(self.agreement.is_due_confirmed())

        services.set_due_date(self.agreement, self.borrower, second)
        self.agreement.refresh_from_db()
        self.assertEqual(self.agreement.due_at, second)
        self.assertIsNotNone(self.agreement.due_borrower_confirmed_at)
        self.assertIsNone(self.agreement.due_owner_confirmed_at)

    def test_start_rejects_expired_due_time(self):
        agree_due_and_start(self.agreement)
        BorrowAgreement.objects.filter(pk=self.agreement.pk).update(
            due_at=timezone.now() - timedelta(minutes=5),
            status=BorrowAgreement.Status.PENDING_DELIVERY,
        )
        self.agreement.refresh_from_db()
        with self.assertRaises(LoanError):
            services.start_borrow(self.agreement)

    def test_return_needs_both_confirmations(self):
        agree_due_and_start(self.agreement)

        services.confirm_return(self.agreement, self.borrower)
        self.agreement.refresh_from_db()
        self.assertEqual(self.agreement.status, BorrowAgreement.Status.AWAITING_RETURN)
        self.assertIsNotNone(self.agreement.handed_back_at)
        self.assertIsNone(self.agreement.completed_at)
        self.assertEqual(self.refunds.calls, [])

        services.confirm_return(self.agreement, self.owner)
        self.agreement.refresh_from_db()
        self.assertEqual(self.agreement.status, BorrowAgreement.Status.RETURNED)
        self.assertIsNotNone(self.agreement.completed_at)
        self.assertEqual(len(self.refunds.calls), 1)
        self.assertEqual(self.refunds.calls[0]["reason"], "normal_return")
        self.assertEqual(self.ended.calls[0]["outcome"], "returned")

        services.confirm_return(self.agreement, self.owner)
        self.assertEqual(len(self.refunds.calls), 1)

    def test_owner_cannot_confirm_return_before_borrower(self):
        agree_due_and_start(self.agreement)
        with self.assertRaises(LoanError):
            services.confirm_return(self.agreement, self.owner)

    def test_non_party_cannot_confirm_or_set_due_date(self):
        with self.assertRaises(PermissionDenied):
            services.set_due_date(self.agreement, self.outsider, timezone.now() + timedelta(days=2))
        agree_due_and_start(self.agreement)
        with self.assertRaises(PermissionDenied):
            services.confirm_return(self.agreement, self.outsider)

    def test_unstarted_agreement_can_be_cancelled_once(self):
        services.cancel_unstarted_agreement(self.agreement, "时间不合适")
        self.agreement.refresh_from_db()
        self.assertEqual(self.agreement.status, BorrowAgreement.Status.CANCELLED)
        self.assertEqual(self.ended.calls[0]["outcome"], "cancelled")
        with self.assertRaises(LoanError):
            services.start_borrow(self.agreement)
