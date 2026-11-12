from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import IdentityApplication
from apps.accounts.services import revoke_identity
from apps.catalog.models import Item
from apps.catalog.services import create_item, edit_item, relist_item, review_item
from apps.loans import services as loans
from apps.loans.models import BorrowAgreement, Dispute, Notification
from apps.payments.models import PaymentOperation
from apps.payments.services import request_refund
from apps.transfers import services as transfers
from apps.transfers.models import Application, Transfer


class MarketIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model()
        cls.admin = users.objects.create_user(username="reviewer", is_staff=True)
        cls.owner = users.objects.create_user(username="owner")
        cls.recipient = users.objects.create_user(username="recipient")
        cls.other = users.objects.create_user(username="other")
        for user in (cls.owner, cls.recipient, cls.other):
            IdentityApplication.objects.create(
                user=user,
                name="演示用户",
                staff_no=f"DEMO-{user.pk}",
                department="演示院系",
                status=IdentityApplication.Status.APPROVED,
                reviewed_by=cls.admin,
            )

    def _post(self, user, route, pk, data=None):
        self.client.force_login(user)
        response = self.client.post(reverse(route, args=[pk]), data or {})
        self.assertEqual(response.status_code, 302, response.content)
        return response

    def _item(self, kind):
        item = create_item(
            owner=self.owner,
            name="演示物品",
            category="演示",
            description="联调测试",
            flow_type=kind,
            owner_nickname="物主",
            campus_area="演示校区",
            contact="私密联系方式",
            location="私密交付地点",
            price=Decimal("25.00") if kind == Item.FlowType.SALE else None,
            deposit_display=Decimal("40.00") if kind == Item.FlowType.LOAN else None,
        )
        return review_item(actor=self.admin, item_id=item.pk, approve=True, reason="")

    def _reserve(self, item):
        self._post(self.recipient, "transfers:apply", item.pk)
        application = Application.objects.get(item=item, applicant=self.recipient)
        self._post(self.owner, "transfers:reserve", application.pk)
        return Transfer.objects.get(application=application)

    def _receipt(self, operation, result="success"):
        call_command(
            "simulate_receipt", operation_id=operation.pk, result=result, stdout=StringIO()
        )

    def _confirm_delivery(self, transfer):
        self._post(self.owner, "transfers:confirm_delivery", transfer.pk)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, Transfer.Status.RESERVED)
        self._post(self.recipient, "transfers:confirm_delivery", transfer.pk)
        transfer.refresh_from_db()

    def _start_loan(self, item):
        transfer = self._reserve(item)
        agreement = transfer.borrow_agreement
        self._post(self.recipient, "payments:pay", transfer.pk)
        self.assertFalse(transfer.payment_operations.exists())
        due = timezone.localtime(timezone.now() + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M")
        self._post(
            self.owner,
            "loans:set_due_date",
            agreement.pk,
            {
                "due_at": due,
                "deposit_amount": "55.00",
            },
        )
        agreement.refresh_from_db()
        self._post(
            self.recipient, "loans:confirm_due_date", agreement.pk, {"terms": agreement.terms_key}
        )
        self._post(self.recipient, "payments:pay", transfer.pk)
        payment = transfer.payment_operations.get()
        self.assertEqual(payment.amount, Decimal("55.00"))
        self._receipt(payment)
        self._confirm_delivery(transfer)
        agreement.refresh_from_db()
        self.assertEqual(agreement.status, BorrowAgreement.Status.ACTIVE)
        return transfer, agreement

    def test_gift_reservation_closes_other_application_and_limits_private_fields(self):
        item = self._item(Item.FlowType.GIFT)
        self._post(self.other, "transfers:apply", item.pk)
        transfer = self._reserve(item)
        self.assertEqual(
            item.applications.get(applicant=self.other).status, Application.Status.CLOSED
        )
        item_url = reverse("items:detail", args=[item.pk])
        self.client.force_login(self.recipient)
        self.assertContains(self.client.get(item_url), "私密交付地点")
        self.client.force_login(self.admin)
        self.assertNotContains(self.client.get(item_url), "私密交付地点")
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(item_url).status_code, 403)
        with self.assertRaises(ValidationError):
            edit_item(owner=self.owner, item_id=item.pk, name="修改名称")
        self._confirm_delivery(transfer)
        self.assertEqual(transfer.status, Transfer.Status.DONATION_COMPLETED)
        self.assertFalse(transfer.payment_operations.exists())
        with self.assertRaises(ValidationError):
            relist_item(owner=self.owner, item_id=item.pk)

    def test_admin_can_search_all_transfers_and_view_read_only_history(self):
        gift = self._item(Item.FlowType.GIFT)
        gift.name = "结案赠送"
        gift.save(update_fields=["name"])
        completed = self._reserve(gift)
        self._confirm_delivery(completed)
        active = self._reserve(self._item(Item.FlowType.SALE))
        list_url = reverse("transfers:admin_transfer_list")
        detail_url = reverse("transfers:admin_transfer_detail", args=[completed.pk])
        active_url = reverse("transfers:admin_transfer_detail", args=[active.pk])
        confirm_url = reverse("transfers:confirm_delivery", args=[active.pk])

        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("accounts:home")), list_url)
        records = self.client.get(list_url)
        self.assertContains(records, detail_url)
        self.assertContains(records, active_url)
        filtered = self.client.get(list_url, {"q": gift.name})
        self.assertContains(filtered, detail_url)
        self.assertNotContains(filtered, active_url)
        history = self.client.get(detail_url)
        self.assertContains(history, "赠送完成")
        self.assertContains(history, "确认交付", count=2)
        active_record = self.client.get(active_url)
        self.assertNotContains(active_record, confirm_url)
        self.assertNotContains(active_record, "私密交付地点")
        self.client.post(confirm_url)
        active.refresh_from_db()
        self.assertIsNone(active.owner_confirmed_at)
        self.assertIsNone(active.recipient_confirmed_at)

    def test_transfer_admin_records_require_staff_even_for_a_transfer_party(self):
        transfer = self._reserve(self._item(Item.FlowType.GIFT))
        list_url = reverse("transfers:admin_transfer_list")
        detail_url = reverse("transfers:admin_transfer_detail", args=[transfer.pk])
        party_url = reverse("transfers:transfer_detail", args=[transfer.pk])
        self.client.logout()
        self.assertEqual(self.client.get(list_url).status_code, 302)
        self.client.force_login(self.recipient)
        self.assertEqual(self.client.get(list_url).status_code, 403)
        self.assertEqual(self.client.get(detail_url).status_code, 403)
        self.assertEqual(self.client.get(party_url).status_code, 200)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(party_url).status_code, 403)

    def test_staff_without_model_permissions_can_query_all_business_data(self):
        staff = get_user_model().objects.create_user("staff_reader", is_staff=True)
        transfer, agreement = self._start_loan(self._item(Item.FlowType.LOAN))
        dispute = loans.open_dispute(
            agreement, self.owner, Dispute.Kind.DAMAGE, "争议描述", "只有当事人提交的材料"
        )
        loans.claim_dispute(dispute, self.admin)
        identity = self.owner.identity_applications.get()
        payment = transfer.payment_operations.get()
        notice = self.recipient.loan_notifications.first()
        self.client.force_login(staff)
        self.assertFalse(staff.has_perm("accounts.view_identityapplication"))

        index = self.client.get(reverse("market_data:index"))
        self.assertContains(index, "全站资料")
        self.assertContains(index, "身份申请")
        self.assertContains(index, "模拟资金流水")
        records = (
            ("accounts_identityapplication", identity.pk, identity.staff_no),
            ("catalog_item", transfer.item_id, "私密交付地点"),
            ("loans_dispute", dispute.pk, "只有当事人提交的材料"),
            ("payments_paymentoperation", payment.pk, "55.00"),
            ("loans_notification", notice.pk, notice.title),
        )
        for name, pk, content in records:
            with self.subTest(name=name):
                self.assertContains(
                    self.client.get(reverse(f"market_data:{name}_change", args=[pk])), content
                )

    def test_data_query_is_staff_only_and_never_edits_business_records(self):
        user = self.owner
        user.set_password("example-test-password")
        user.save(update_fields=["password"])
        item = self._item(Item.FlowType.GIFT)
        index_url = reverse("market_data:index")
        item_url = reverse("market_data:catalog_item_change", args=[item.pk])
        user_url = reverse("market_data:auth_user_change", args=[user.pk])

        self.client.force_login(self.recipient)
        for url in (index_url, item_url, user_url):
            self.assertRedirects(
                self.client.get(url),
                f"{reverse('market_data:login')}?next={url}",
                fetch_redirect_response=False,
            )

        self.client.force_login(self.admin)
        user_page = self.client.get(user_url)
        self.assertContains(user_page, user.username)
        self.assertNotContains(user_page, user.password)
        self.assertNotContains(user_page, "id_password")
        response = self.client.post(item_url, {"name": "越权修改", "_save": "1"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            self.client.post(
                reverse("market_data:catalog_item_delete", args=[item.pk])
            ).status_code,
            403,
        )
        item.refresh_from_db()
        self.assertNotEqual(item.name, "越权修改")

    def test_sale_receipt_gates_delivery_and_settlement_requires_its_own_receipt(self):
        transfer = self._reserve(self._item(Item.FlowType.SALE))
        self._post(self.recipient, "payments:pay", transfer.pk)
        payment = transfer.payment_operations.get()
        self.assertEqual(payment.status, PaymentOperation.Status.PAYING)
        self._post(self.owner, "transfers:confirm_delivery", transfer.pk)
        transfer.refresh_from_db()
        self.assertIsNone(transfer.owner_confirmed_at)
        self._receipt(payment)
        self._confirm_delivery(transfer)
        self.assertEqual(transfer.status, Transfer.Status.COMPLETED)
        settlement = transfer.payment_operations.get(kind=PaymentOperation.Kind.SETTLEMENT)
        self.assertEqual(settlement.status, PaymentOperation.Status.SETTLING)
        self._receipt(settlement)
        settlement.refresh_from_db()
        self.assertEqual(settlement.status, PaymentOperation.Status.SETTLED)

    def test_loan_return_refunds_once_and_item_requires_new_review(self):
        item = self._item(Item.FlowType.LOAN)
        transfer, agreement = self._start_loan(item)
        with self.assertRaises(ValidationError):
            request_refund(transfer_id=transfer.pk, reason="尚未归还")
        self._post(self.recipient, "loans:confirm_return", agreement.pk)
        self.assertFalse(
            transfer.payment_operations.filter(kind=PaymentOperation.Kind.REFUND).exists()
        )
        self._post(self.owner, "loans:confirm_return", agreement.pk)
        self._post(self.owner, "loans:confirm_return", agreement.pk)
        refund = transfer.payment_operations.get(kind=PaymentOperation.Kind.REFUND)
        self.assertEqual(refund.amount, Decimal("55.00"))
        self.assertEqual(refund.status, PaymentOperation.Status.REFUNDING)
        transfer.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(transfer.status, Transfer.Status.LOAN_ENDED)
        self.assertEqual(item.display_status, Item.DisplayStatus.OFFLINE)
        self.assertEqual(
            relist_item(owner=self.owner, item_id=item.pk).display_status,
            Item.DisplayStatus.PENDING,
        )

    def test_lost_overdue_loan_closes_pending_application_and_refunds_after_resolution(self):
        item = self._item(Item.FlowType.LOAN)
        transfer, agreement = self._start_loan(item)
        other_item = self._item(Item.FlowType.LOAN)
        self._post(self.recipient, "transfers:apply", other_item.pk)
        pending = Application.objects.get(item=other_item)
        dispute = loans.open_dispute(agreement, self.owner, Dispute.Kind.LOSS, "模拟丢失")
        BorrowAgreement.objects.filter(pk=agreement.pk).update(
            due_at=timezone.now() - timedelta(hours=1)
        )
        call_command("process_market_jobs", stdout=StringIO())
        pending.refresh_from_db()
        self.assertEqual(pending.status, Application.Status.CLOSED)
        self.assertFalse(loans.can_borrow(user_id=self.recipient.pk))
        with self.assertRaises(ValidationError):
            request_refund(transfer_id=transfer.pk, reason="争议尚未结清")
        loans.record_plan(dispute, self.owner, "双方另行处理赔偿")
        for user in (self.owner, self.recipient):
            loans.confirm_plan_performed(dispute, user)
            loans.agree_dispute_end(dispute, user)
        agreement.refresh_from_db()
        self.assertEqual(agreement.status, BorrowAgreement.Status.COMPENSATED)
        self.assertIsNone(agreement.handed_back_at)
        self.assertTrue(loans.can_borrow(user_id=self.recipient.pk))
        self.assertEqual(transfer.payment_operations.get(kind="refund").amount, Decimal("55.00"))
        with self.assertRaises(ValidationError):
            relist_item(owner=self.owner, item_id=item.pk)

    def test_timeout_with_late_receipt_does_not_restore_cancelled_transfer(self):
        item = self._item(Item.FlowType.SALE)
        transfer = self._reserve(item)
        self._post(self.recipient, "payments:pay", transfer.pk)
        payment = transfer.payment_operations.get()
        self._receipt(payment, "unknown")
        Transfer.objects.filter(pk=transfer.pk).update(
            reserved_at=timezone.now() - timedelta(hours=24)
        )
        call_command("process_market_jobs", stdout=StringIO())
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, Transfer.Status.RESERVED)
        self._receipt(payment, "failure")
        call_command("process_market_jobs", stdout=StringIO())
        transfer.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(transfer.status, Transfer.Status.CANCELLED)
        self.assertEqual(item.display_status, Item.DisplayStatus.AVAILABLE)
        self._receipt(payment)
        call_command("process_market_jobs", stdout=StringIO())
        call_command("process_market_jobs", stdout=StringIO())
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, Transfer.Status.CANCELLED)
        self.assertEqual(transfer.payment_operations.filter(kind="refund").count(), 1)

    def test_revoked_identity_does_not_break_cancellation_or_reopen_item(self):
        item = self._item(Item.FlowType.LOAN)
        transfer = self._reserve(item)
        revoke_identity(actor=self.admin, user_id=self.owner.pk, reason="联调撤销")
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.recipient,
                event="transfer.identity_revoked",
                business_ref=str(transfer.pk),
            ).exists()
        )
        transfers.cancel_before_delivery(
            actor=self.recipient, transfer_id=transfer.pk, reason="主动取消"
        )
        item.refresh_from_db()
        self.assertEqual(item.display_status, Item.DisplayStatus.OFFLINE)
        self.assertEqual(transfer.borrow_agreement.status, BorrowAgreement.Status.CANCELLED)

    def test_market_search_filters_public_items_and_shows_pending_application(self):
        gift = self._item(Item.FlowType.GIFT)
        gift.name = "高等数学讲义"
        gift.save(update_fields=["name"])
        sale = self._item(Item.FlowType.SALE)
        sale.name = "高等数学练习册"
        sale.save(update_fields=["name"])
        result = self.client.get(reverse("items:list"), {"q": "高等数学", "flow": "赠送"})
        self.assertContains(result, gift.name)
        self.assertNotContains(result, sale.name)

        item_url = reverse("items:detail", args=[gift.pk])
        self.assertContains(self.client.get(item_url), "登录后申请")
        self.client.force_login(self.recipient)
        self.assertContains(self.client.get(item_url), "申请领取")
        self._post(self.recipient, "transfers:apply", gift.pk)
        page = self.client.get(item_url)
        self.assertContains(page, "你已提交申请")
        self.assertNotContains(page, "申请领取")

    def test_account_uses_consistent_publish_action_and_user_facing_copy(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("accounts:home"))
        self.assertContains(response, "发布物品")
        self.assertContains(response, "身份申请记录")
        self.assertContains(response, self.owner.username)
        self.assertNotContains(response, "发布第一件物品")
        self.assertNotContains(response, "CP-D-02")

    def test_stale_form_page_gives_recovery_steps(self):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.owner)
        response = browser.post(reverse("items:create"))
        self.assertContains(response, "这次操作没有提交", status_code=403)
        self.assertContains(response, self.owner.username, status_code=403)
        self.assertNotContains(response, "CSRF", status_code=403)

    def test_payment_actions_follow_role_status_and_deadline(self):
        transfer = self._reserve(self._item(Item.FlowType.SALE))
        url = reverse("payments:payments_for_transfer", args=[transfer.pk])
        self.client.force_login(self.owner)
        self.assertNotContains(self.client.get(url), "发起模拟付款")
        self.client.force_login(self.recipient)
        self.assertContains(self.client.get(url), "发起模拟付款")
        self._post(self.recipient, "payments:pay", transfer.pk)
        self.assertNotContains(self.client.get(url), "发起模拟付款")
        self.assertContains(self.client.get(url), "正在等待付款结果")
        payment = transfer.payment_operations.get()
        self._receipt(payment, "failure")
        self.assertContains(self.client.get(url), "重新发起模拟付款")
        Transfer.objects.filter(pk=transfer.pk).update(
            reserved_at=timezone.now() - timedelta(hours=25),
        )
        response = self.client.get(url)
        self.assertContains(response, "付款期限已结束")
        self.assertNotContains(response, "重新发起模拟付款")

    def test_old_borrow_terms_cannot_confirm_new_amount(self):
        transfer = self._reserve(self._item(Item.FlowType.LOAN))
        agreement = transfer.borrow_agreement
        due = timezone.now() + timedelta(days=2)
        terms = loans.set_due_date(agreement, self.owner, due).terms_key
        loans.set_due_date(agreement, self.owner, due, Decimal("75.00"))
        self._post(self.recipient, "loans:confirm_due_date", agreement.pk, {"terms": terms})
        agreement.refresh_from_db()
        self.assertIsNone(agreement.due_borrower_confirmed_at)
        self.assertContains(
            self.client.get(reverse("loans:detail", args=[agreement.pk])),
            "借用约定已更新",
        )
        self._post(
            self.recipient, "loans:confirm_due_date", agreement.pk, {"terms": agreement.terms_key}
        )
        agreement.refresh_from_db()
        self.assertTrue(agreement.is_due_confirmed())

    def test_updated_dispute_plan_requires_fresh_confirmation(self):
        _, agreement = self._start_loan(self._item(Item.FlowType.LOAN))
        dispute = loans.open_dispute(agreement, self.owner, Dispute.Kind.DAMAGE, "演示损坏")
        dispute = loans.record_plan(dispute, self.owner, "原方案")
        old_plan = dispute.plan_key
        loans.confirm_plan_performed(dispute, self.owner)
        loans.record_plan(dispute, self.recipient, "更新后的方案")
        self._post(self.owner, "loans:confirm_performed", dispute.pk, {"plan": old_plan})
        dispute.refresh_from_db()
        self.assertIsNone(dispute.owner_performed_at)
        self.assertContains(
            self.client.get(reverse("loans:dispute_detail", args=[dispute.pk])),
            "处理方案已更新",
        )
        self._post(self.owner, "loans:confirm_performed", dispute.pk, {"plan": dispute.plan_key})
        dispute.refresh_from_db()
        self.assertIsNotNone(dispute.owner_performed_at)
