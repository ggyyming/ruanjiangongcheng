from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.utils import timezone

from apps.loans import services
from apps.loans.models import BorrowAgreement, ExtensionRequest
from apps.loans.services import LoanError

from .factories import agree_due_and_start, make_agreement, make_user


class ExtensionTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner")
        self.borrower = make_user("borrower")
        self.agreement = agree_due_and_start(make_agreement(self.owner, self.borrower))

    def test_pending_request_does_not_change_due_date(self):
        original = self.agreement.due_at
        proposed = original + timedelta(days=3)
        extension = services.request_extension(self.agreement, self.borrower, proposed)

        self.agreement.refresh_from_db()
        self.assertEqual(self.agreement.due_at, original)
        self.assertEqual(extension.status, ExtensionRequest.Status.PENDING)
        self.assertEqual(extension.previous_due_at, original)

    def test_owner_approval_updates_due_and_keeps_history(self):
        original = self.agreement.due_at
        proposed = original + timedelta(days=3)
        extension = services.request_extension(self.agreement, self.borrower, proposed)
        services.decide_extension(extension, self.owner, approve=True)

        self.agreement.refresh_from_db()
        extension.refresh_from_db()
        self.assertEqual(self.agreement.due_at, proposed)
        self.assertEqual(extension.status, ExtensionRequest.Status.APPROVED)
        self.assertEqual(extension.previous_due_at, original)
        self.assertEqual(self.agreement.extensions.count(), 1)

    def test_request_after_due_time_is_rejected(self):
        BorrowAgreement.objects.filter(pk=self.agreement.pk).update(
            due_at=timezone.now() - timedelta(minutes=1)
        )
        self.agreement.refresh_from_db()
        with self.assertRaises(LoanError):
            services.request_extension(
                self.agreement, self.borrower, timezone.now() + timedelta(days=1)
            )

    def test_owner_cannot_request_and_borrower_cannot_approve(self):
        proposed = self.agreement.due_at + timedelta(days=2)
        with self.assertRaises(LoanError):
            services.request_extension(self.agreement, self.owner, proposed)

        extension = services.request_extension(self.agreement, self.borrower, proposed)
        with self.assertRaises(PermissionDenied):
            services.decide_extension(extension, self.borrower, approve=True)

    def test_rejection_keeps_original_due_time(self):
        original = self.agreement.due_at
        extension = services.request_extension(
            self.agreement, self.borrower, original + timedelta(days=2)
        )
        services.decide_extension(extension, self.owner, approve=False)
        self.agreement.refresh_from_db()
        self.assertEqual(self.agreement.due_at, original)
        extension.refresh_from_db()
        self.assertEqual(extension.status, ExtensionRequest.Status.REJECTED)

    def test_second_pending_extension_is_rejected(self):
        original = self.agreement.due_at
        services.request_extension(self.agreement, self.borrower, original + timedelta(days=2))
        with self.assertRaises(LoanError):
            services.request_extension(self.agreement, self.borrower, original + timedelta(days=4))

    def test_cross_period_approval_keeps_overdue_record_and_restriction(self):
        original = self.agreement.due_at
        proposed = timezone.now() + timedelta(days=5)
        extension = services.request_extension(self.agreement, self.borrower, proposed)

        BorrowAgreement.objects.filter(pk=self.agreement.pk).update(
            due_at=timezone.now() - timedelta(hours=1)
        )
        self.agreement.refresh_from_db()
        services.scan_overdue()
        self.agreement.refresh_from_db()
        self.assertIsNotNone(self.agreement.overdue_marked_at)
        self.assertTrue(services.is_borrow_restricted(self.borrower))

        services.decide_extension(extension, self.owner, approve=True)
        self.agreement.refresh_from_db()
        self.assertEqual(self.agreement.due_at, proposed)
        self.assertIsNotNone(self.agreement.overdue_marked_at)
        self.assertTrue(services.is_borrow_restricted(self.borrower))
        self.assertNotEqual(self.agreement.due_at, original)

    def test_approval_requires_new_due_after_approval_time(self):
        extension = services.request_extension(
            self.agreement, self.borrower, self.agreement.due_at + timedelta(days=1)
        )
        ExtensionRequest.objects.filter(pk=extension.pk).update(
            proposed_due_at=timezone.now() - timedelta(minutes=1)
        )
        with self.assertRaises(LoanError):
            services.decide_extension(extension, self.owner, approve=True)
