import os
import shutil
import tempfile
from io import BytesIO
from unittest.mock import patch

from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.loans import services
from apps.loans.models import Dispute, DisputeAttachment, DisputeEvent

from .factories import agree_due_and_start, make_agreement, make_user


def image_bytes(image_format="PNG", size=(20, 20)):
    buffer = BytesIO()
    Image.new("RGB", size, "white").save(buffer, format=image_format)
    return buffer.getvalue()


def image_upload(name="evidence.png", image_format="PNG", size=(20, 20)):
    content_type = "image/png" if image_format == "PNG" else "image/jpeg"
    return SimpleUploadedFile(name, image_bytes(image_format, size), content_type=content_type)


class DisputeAttachmentTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        media = override_settings(MEDIA_ROOT=self.media_root)
        media.enable()
        self.addCleanup(media.disable)
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)

        self.owner = make_user("owner")
        self.borrower = make_user("borrower")
        self.outsider = make_user("outsider")
        self.admin = make_user("admin", is_staff=True)
        self.other_admin = make_user("other-admin", is_staff=True)
        self.root = make_user("root", is_staff=True, is_superuser=True)
        self.agreement = agree_due_and_start(make_agreement(self.owner, self.borrower))
        self.dispute = services.open_dispute(
            self.agreement, self.borrower, Dispute.Kind.DAMAGE, "镜头有划痕"
        )

    def upload(self, user, *, dispute=None, upload=None):
        self.client.force_login(user)
        return self.client.post(
            reverse("loans:add_attachment", args=[(dispute or self.dispute).pk]),
            {"file": upload or image_upload()},
        )

    def download(self, user, attachment, *, dispute=None):
        self.client.force_login(user)
        return self.client.get(
            reverse(
                "loans:download_attachment",
                args=[(dispute or self.dispute).pk, attachment.pk],
            )
        )

    def test_parties_can_upload_and_metadata_is_recorded(self):
        self.upload(self.owner, upload=image_upload("owner.png"))
        self.upload(self.borrower, upload=image_upload("borrower.jpg", "JPEG"))

        self.assertEqual(self.dispute.attachments.count(), 2)
        owner_attachment = self.dispute.attachments.get(uploaded_by=self.owner)
        borrower_attachment = self.dispute.attachments.get(uploaded_by=self.borrower)
        self.assertEqual(owner_attachment.original_name, "owner.png")
        self.assertEqual(owner_attachment.content_type, "image/png")
        self.assertEqual(borrower_attachment.content_type, "image/jpeg")
        self.assertGreater(owner_attachment.size, 0)
        self.assertTrue(owner_attachment.storage_key.startswith("disputes/"))
        self.assertTrue(default_storage.exists(owner_attachment.storage_key))
        self.assertEqual(
            DisputeEvent.objects.filter(dispute=self.dispute, action="attachment_added").count(),
            2,
        )

    def test_assigned_admin_can_download(self):
        data = image_bytes("PNG")
        self.upload(
            self.owner,
            upload=SimpleUploadedFile("evidence.png", data, content_type="image/png"),
        )
        attachment = self.dispute.attachments.get()
        services.claim_dispute(self.dispute, self.admin)

        response = self.download(self.admin, attachment)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), data)
        self.assertIn("evidence.png", response["Content-Disposition"])
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_unrelated_users_cannot_download(self):
        self.upload(self.owner)
        attachment = self.dispute.attachments.get()

        for user in (self.outsider, self.other_admin, self.root):
            self.assertEqual(self.download(user, attachment).status_code, 403)

        for user in (self.owner, self.borrower):
            response = self.download(user, attachment)
            self.assertEqual(response.status_code, 200)
            response.close()

    def test_attachment_from_another_dispute_is_rejected(self):
        self.upload(self.owner)
        attachment = self.dispute.attachments.get()

        other_agreement = agree_due_and_start(
            make_agreement(self.owner, self.borrower, item_title="手机")
        )
        other_dispute = services.open_dispute(
            other_agreement, self.borrower, Dispute.Kind.DAMAGE, "屏幕碎裂"
        )
        self.assertEqual(
            self.download(self.owner, attachment, dispute=other_dispute).status_code, 404
        )

        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("loans:download_attachment", args=[self.dispute.pk, attachment.pk + 999])
        )
        self.assertEqual(response.status_code, 404)

    def test_disguised_file_is_rejected(self):
        response = self.upload(
            self.owner,
            upload=SimpleUploadedFile("fake.png", b"not an image", content_type="image/png"),
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.dispute.attachments.count(), 0)
        self.assertEqual(os.listdir(self.media_root), [])

    def test_oversized_file_is_rejected(self):
        self.assertEqual(DisputeAttachment.MAX_BYTES, 5 * 1024 * 1024)
        with patch.object(DisputeAttachment, "MAX_BYTES", 10):
            response = self.upload(self.owner)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.dispute.attachments.count(), 0)
        self.assertEqual(os.listdir(self.media_root), [])

    def test_oversized_dimensions_are_rejected(self):
        response = self.upload(self.owner, upload=image_upload(size=(4097, 10)))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.dispute.attachments.count(), 0)
        self.assertEqual(os.listdir(self.media_root), [])

    def test_sixth_attachment_is_rejected(self):
        for _ in range(DisputeAttachment.MAX_PER_DISPUTE):
            self.assertEqual(self.upload(self.owner).status_code, 302)
        self.assertEqual(self.dispute.attachments.count(), DisputeAttachment.MAX_PER_DISPUTE)

        response = self.upload(self.borrower)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.dispute.attachments.count(), DisputeAttachment.MAX_PER_DISPUTE)

    def test_admin_cannot_upload(self):
        services.claim_dispute(self.dispute, self.admin)
        response = self.upload(self.admin)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.dispute.attachments.count(), 0)

    def test_closed_dispute_rejects_upload_but_keeps_download(self):
        self.upload(self.owner)
        attachment = self.dispute.attachments.get()

        services.record_plan(self.dispute, self.borrower, "赔偿 50 元")
        services.confirm_plan_performed(self.dispute, self.owner)
        services.confirm_plan_performed(self.dispute, self.borrower)
        services.agree_dispute_end(self.dispute, self.owner)
        services.agree_dispute_end(self.dispute, self.borrower)
        self.dispute.refresh_from_db()
        self.assertEqual(self.dispute.status, Dispute.Status.CLOSED)

        response = self.upload(self.owner)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.dispute.attachments.count(), 1)

        response = self.download(self.owner, attachment)
        self.assertEqual(response.status_code, 200)
        response.close()

    def test_missing_file_returns_404(self):
        self.upload(self.owner)
        attachment = self.dispute.attachments.get()
        default_storage.delete(attachment.storage_key)

        response = self.download(self.owner, attachment)
        self.assertEqual(response.status_code, 404)

    def test_download_still_authorizes_with_debug_false(self):
        self.upload(self.owner)
        attachment = self.dispute.attachments.get()

        with self.settings(DEBUG=False):
            response = self.download(self.borrower, attachment)
            self.assertEqual(response.status_code, 200)
            response.close()
            self.assertEqual(self.download(self.outsider, attachment).status_code, 403)

    def test_attachment_is_not_registered_in_data_console(self):
        from config.data_admin import data_site

        self.assertNotIn(DisputeAttachment, data_site._registry)
