from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.loans import services
from apps.loans.models import BorrowAgreement, Dispute, Notification

from .factories import agree_due_and_start, make_agreement, make_user


class ViewTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner")
        self.borrower = make_user("borrower")
        self.outsider = make_user("outsider")
        self.admin = make_user("admin", is_staff=True)
        self.other_admin = make_user("other-admin", is_staff=True)
        self.agreement = make_agreement(self.owner, self.borrower)

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("loans:list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_list_only_shows_own_agreements(self):
        self.client.force_login(self.outsider)
        response = self.client.get(reverse("loans:list"))
        self.assertNotContains(response, "相机")

        self.client.force_login(self.borrower)
        response = self.client.get(reverse("loans:list"))
        self.assertContains(response, "相机")

    def test_detail_rejects_non_party(self):
        self.client.force_login(self.outsider)
        response = self.client.get(reverse("loans:detail", args=[self.agreement.pk]))
        self.assertEqual(response.status_code, 403)

        self.client.force_login(self.owner)
        response = self.client.get(reverse("loans:detail", args=[self.agreement.pk]))
        self.assertEqual(response.status_code, 200)

    def test_detail_renders_for_active_borrower(self):
        agree_due_and_start(self.agreement)
        self.client.force_login(self.borrower)
        response = self.client.get(reverse("loans:detail", args=[self.agreement.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "借用中")
        self.assertContains(response, "申请延期")

    def test_due_date_post_records_only_submitter_side(self):
        due = timezone.localtime(timezone.now() + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M")
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("loans:set_due_date", args=[self.agreement.pk]), {"due_at": due}
        )
        self.assertEqual(response.status_code, 302)

        self.agreement.refresh_from_db()
        self.assertIsNotNone(self.agreement.due_at)
        self.assertIsNotNone(self.agreement.due_owner_confirmed_at)
        self.assertIsNone(self.agreement.due_borrower_confirmed_at)

    def test_invalid_due_date_is_rejected(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("loans:set_due_date", args=[self.agreement.pk]), {"due_at": "昨天"}
        )
        self.assertEqual(response.status_code, 302)
        self.agreement.refresh_from_db()
        self.assertIsNone(self.agreement.due_at)

    def test_return_through_views(self):
        agree_due_and_start(self.agreement)
        self.client.force_login(self.borrower)
        self.client.post(reverse("loans:confirm_return", args=[self.agreement.pk]))
        self.agreement.refresh_from_db()
        self.assertEqual(self.agreement.status, BorrowAgreement.Status.AWAITING_RETURN)

        self.client.force_login(self.owner)
        self.client.post(reverse("loans:confirm_return", args=[self.agreement.pk]))
        self.agreement.refresh_from_db()
        self.assertEqual(self.agreement.status, BorrowAgreement.Status.RETURNED)

    def test_get_actions_are_rejected(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("loans:confirm_return", args=[self.agreement.pk]))
        self.assertEqual(response.status_code, 405)

    def test_extension_can_only_be_requested_by_borrower(self):
        agree_due_and_start(self.agreement)
        proposed = timezone.localtime(self.agreement.due_at + timedelta(days=2)).strftime(
            "%Y-%m-%dT%H:%M"
        )
        self.client.force_login(self.owner)
        self.client.post(
            reverse("loans:request_extension", args=[self.agreement.pk]),
            {"proposed_due_at": proposed},
        )
        self.assertEqual(self.agreement.extensions.count(), 0)

        self.client.force_login(self.borrower)
        self.client.post(
            reverse("loans:request_extension", args=[self.agreement.pk]),
            {"proposed_due_at": proposed},
        )
        self.assertEqual(self.agreement.extensions.count(), 1)

    def test_dispute_material_access(self):
        agree_due_and_start(self.agreement)
        dispute = services.open_dispute(
            self.agreement, self.borrower, Dispute.Kind.DAMAGE, "镜头进灰"
        )
        url = reverse("loans:dispute_detail", args=[dispute.pk])

        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(url).status_code, 403)

        self.client.force_login(self.owner)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "镜头进灰")

        self.client.force_login(self.other_admin)
        self.client.post(reverse("loans:claim_dispute", args=[dispute.pk]))
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(
            self.client.get(reverse("loans:admin_dispute_detail", args=[dispute.pk])).status_code,
            403,
        )

    def test_admin_pages_require_staff(self):
        self.client.force_login(self.borrower)
        self.assertEqual(self.client.get(reverse("loans:admin_dispute_list")).status_code, 403)

        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("loans:admin_dispute_list")).status_code, 200)

    def test_notifications_are_private_and_read_state_is_separate(self):
        own = Notification.objects.filter(recipient=self.owner).first()
        self.assertIsNotNone(own)

        self.client.force_login(self.borrower)
        self.assertEqual(
            self.client.post(reverse("loans:mark_notification_read", args=[own.pk])).status_code,
            404,
        )

        self.client.force_login(self.owner)
        response = self.client.get(reverse("loans:notifications"))
        self.assertEqual(response.status_code, 200)
        self.client.post(reverse("loans:mark_notification_read", args=[own.pk]))
        own.refresh_from_db()
        self.assertIsNotNone(own.read_at)
        self.agreement.refresh_from_db()
        self.assertEqual(self.agreement.status, BorrowAgreement.Status.PENDING_DELIVERY)
