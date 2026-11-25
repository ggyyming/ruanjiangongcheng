"""撤销去向分歧：管理员接单与双确认的服务层测试（CP-BR-09/10、CP-R-12/13/25）。

覆盖下一轮模块 B 的验收用例 B1～B6。
"""

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import IdentityApplication
from apps.catalog.models import Item
from apps.transfers import services
from apps.transfers.models import (
    Application,
    Revocation,
    RevocationConflict,
    RevocationRound,
    Transfer,
)

User = get_user_model()


def _item(owner, kind="sale", price="10.00"):
    IdentityApplication.objects.create(user=owner, status=IdentityApplication.Status.APPROVED)
    return Item.objects.create(
        owner=owner,
        flow_type=Item.FlowType.SALE,
        price=Decimal(price),
        deposit_display=Decimal("20.00"),
        name="测试物品",
        display_status=Item.DisplayStatus.AVAILABLE,
    )


class RevocationConflictTestCase(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner")
        self.buyer = User.objects.create_user(username="buyer")
        self.admin = User.objects.create_user(username="admin", is_staff=True)
        self.admin2 = User.objects.create_user(username="admin2", is_staff=True)
        IdentityApplication.objects.create(
            user=self.buyer, status=IdentityApplication.Status.APPROVED
        )
        self.item = _item(self.owner, kind="sale", price="10.00")
        self.app = Application.objects.create(
            item=self.item, applicant=self.buyer, kind=Application.Kind.SALE
        )
        with patch("apps.catalog.services.change_availability"):
            self.transfer = services.reserve(actor=self.owner, application_id=self.app.id)

    def _start_conflict(self):
        """一方已确认交付，双方同意撤销但去向不同 -> 建立待认领处理记录。"""
        self.transfer.owner_confirmed_at = timezone.now()
        self.transfer.save(update_fields=["owner_confirmed_at"])
        services.start_revoke(actor=self.buyer, transfer_id=self.transfer.id, reason="想撤销")
        services.declare_direction(
            actor=self.buyer, transfer_id=self.transfer.id, direction="not_handed_over"
        )
        services.agree_revoke(actor=self.owner, transfer_id=self.transfer.id)
        services.declare_direction(
            actor=self.owner, transfer_id=self.transfer.id, direction="returned"
        )
        self.revocation = Revocation.objects.get(transfer=self.transfer)
        self.conflict = RevocationConflict.objects.get(revocation=self.revocation)

    def test_b1_conflict_created_no_refund(self):
        with patch("apps.payments.services.request_refund") as refund:
            self._start_conflict()
        self.transfer.refresh_from_db()
        self.assertEqual(self.conflict.status, RevocationConflict.Status.OPEN)
        self.assertEqual(self.transfer.status, Transfer.Status.RESERVED)
        self.assertEqual(self.transfer.revoke_status, Transfer.RevokeStatus.NEGOTIATING)
        refund.assert_not_called()

    def test_b1_conflict_appears_in_pending_once(self):
        self._start_conflict()
        self.assertEqual(
            list(services.pending_revocation_conflicts().values_list("pk", flat=True)),
            [self.conflict.pk],
        )

    def test_b2_only_one_admin_claims(self):
        self._start_conflict()
        claimed = services.claim_revocation_conflict(actor=self.admin, conflict_id=self.conflict.pk)
        self.assertEqual(claimed.assigned_admin_id, self.admin.id)
        self.assertEqual(claimed.status, RevocationConflict.Status.IN_PROGRESS)
        with self.assertRaises(ValidationError):
            services.claim_revocation_conflict(actor=self.admin2, conflict_id=self.conflict.pk)
        # 本人重复认领幂等
        again = services.claim_revocation_conflict(actor=self.admin, conflict_id=self.conflict.pk)
        self.assertEqual(again.assigned_admin_id, self.admin.id)

    def test_b2_non_staff_cannot_claim(self):
        self._start_conflict()
        with self.assertRaises(PermissionDenied):
            services.claim_revocation_conflict(actor=self.buyer, conflict_id=self.conflict.pk)

    def test_b3_round_double_confirm_completes_with_single_refund(self):
        self._start_conflict()
        services.claim_revocation_conflict(actor=self.admin, conflict_id=self.conflict.pk)
        round_ = services.start_revocation_round(
            actor=self.admin, conflict_id=self.conflict.pk, instruction="请双方确认未交出"
        )
        with (
            patch("apps.catalog.services.change_availability") as availability,
            patch("apps.payments.services.is_paid", return_value=True),
            patch("apps.loans.services.has_open_dispute", return_value=False),
            patch("apps.payments.services.request_refund") as refund,
        ):
            # 单方提交不足以撤销
            services.declare_revocation_round(
                actor=self.owner,
                conflict_id=self.conflict.pk,
                round_id=round_.pk,
                direction="not_handed_over",
            )
            self.transfer.refresh_from_db()
            self.assertEqual(self.transfer.status, Transfer.Status.RESERVED)
            self.assertFalse(refund.called)
            # 另一方确认相同结果 -> 撤销生效
            services.declare_revocation_round(
                actor=self.buyer,
                conflict_id=self.conflict.pk,
                round_id=round_.pk,
                direction="not_handed_over",
            )
        self.transfer.refresh_from_db()
        self.conflict.refresh_from_db()
        self.assertEqual(self.transfer.status, Transfer.Status.REVOKED)
        self.assertEqual(self.conflict.status, RevocationConflict.Status.RESOLVED)
        refund.assert_called_once()
        availability.assert_called_once()

    def test_b4_stale_round_rejected(self):
        self._start_conflict()
        services.claim_revocation_conflict(actor=self.admin, conflict_id=self.conflict.pk)
        round1 = services.start_revocation_round(
            actor=self.admin, conflict_id=self.conflict.pk, instruction="第一轮"
        )
        services.declare_revocation_round(
            actor=self.owner,
            conflict_id=self.conflict.pk,
            round_id=round1.pk,
            direction="not_handed_over",
        )
        services.declare_revocation_round(
            actor=self.buyer, conflict_id=self.conflict.pk, round_id=round1.pk, direction="returned"
        )
        round1.refresh_from_db()
        self.assertEqual(round1.result, RevocationRound.Result.CONFLICT)

        round2 = services.start_revocation_round(
            actor=self.admin, conflict_id=self.conflict.pk, instruction="第二轮"
        )
        # 旧轮次提交被拒绝
        with self.assertRaises(ValidationError):
            services.declare_revocation_round(
                actor=self.owner,
                conflict_id=self.conflict.pk,
                round_id=round1.pk,
                direction="not_handed_over",
            )
        # 本轮双方确认一致 -> 完成
        with (
            patch("apps.catalog.services.change_availability"),
            patch("apps.payments.services.is_paid", return_value=False),
        ):
            services.declare_revocation_round(
                actor=self.owner,
                conflict_id=self.conflict.pk,
                round_id=round2.pk,
                direction="not_handed_over",
            )
            services.declare_revocation_round(
                actor=self.buyer,
                conflict_id=self.conflict.pk,
                round_id=round2.pk,
                direction="not_handed_over",
            )
        self.transfer.refresh_from_db()
        self.assertEqual(self.transfer.status, Transfer.Status.REVOKED)

    def test_b5_withdraw_after_claim_closes_entry(self):
        self._start_conflict()
        services.claim_revocation_conflict(actor=self.admin, conflict_id=self.conflict.pk)
        round_ = services.start_revocation_round(
            actor=self.admin, conflict_id=self.conflict.pk, instruction="请确认"
        )
        services.withdraw_revoke(actor=self.buyer, transfer_id=self.transfer.id)
        services.withdraw_revoke(actor=self.owner, transfer_id=self.transfer.id)
        self.transfer.refresh_from_db()
        self.conflict.refresh_from_db()
        self.assertEqual(self.transfer.revoke_status, Transfer.RevokeStatus.NONE)
        self.assertEqual(self.conflict.status, RevocationConflict.Status.CLOSED)
        # 旧确认链接不可继续操作
        with self.assertRaises(ValidationError):
            services.declare_revocation_round(
                actor=self.owner,
                conflict_id=self.conflict.pk,
                round_id=round_.pk,
                direction="not_handed_over",
            )

    def test_b6_backfill_picks_up_old_conflicting_records(self):
        self._start_conflict()
        self.conflict.delete()  # 模拟迁移前尚未建档的冲突协商
        created = services.backfill_revocation_conflicts()
        self.assertEqual(created, 1)
        pending = list(services.pending_revocation_conflicts().values_list("pk", flat=True))
        self.assertEqual(len(pending), 1)
        self.assertEqual(
            services.claim_revocation_conflict(actor=self.admin, conflict_id=pending[0]).status,
            RevocationConflict.Status.IN_PROGRESS,
        )

    def test_round_declare_idempotent_no_overwrite(self):
        self._start_conflict()
        services.claim_revocation_conflict(actor=self.admin, conflict_id=self.conflict.pk)
        round_ = services.start_revocation_round(
            actor=self.admin, conflict_id=self.conflict.pk, instruction="请确认"
        )
        services.declare_revocation_round(
            actor=self.owner,
            conflict_id=self.conflict.pk,
            round_id=round_.pk,
            direction="not_handed_over",
        )
        services.declare_revocation_round(
            actor=self.owner,
            conflict_id=self.conflict.pk,
            round_id=round_.pk,
            direction="returned",
        )
        round_.refresh_from_db()
        self.assertEqual(round_.owner_direction, "not_handed_over")

    # 网页路由冒烟测试：校验 URL 接线与模板渲染（对应“重点验证相关网页路由”）
    def test_view_admin_claim_round_flow(self):
        self._start_conflict()
        admin_client = Client()
        admin_client.force_login(self.admin)
        resp = admin_client.get(reverse("transfers:admin_revocation_conflicts"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "撤销去向分歧")

        resp = admin_client.post(
            reverse("transfers:claim_revocation_conflict", args=[self.conflict.pk])
        )
        self.assertRedirects(
            resp, reverse("transfers:revocation_conflict_detail", args=[self.conflict.pk])
        )

        resp = admin_client.get(
            reverse("transfers:revocation_conflict_detail", args=[self.conflict.pk])
        )
        self.assertEqual(resp.status_code, 200)

        resp = admin_client.post(
            reverse("transfers:start_revocation_round", args=[self.conflict.pk]),
            {"instruction": "请双方确认未交出"},
        )
        self.assertEqual(resp.status_code, 302)
        round_ = RevocationRound.objects.get(conflict=self.conflict)

        buyer_client = Client()
        buyer_client.force_login(self.buyer)
        resp = buyer_client.post(
            reverse("transfers:declare_revocation_round", args=[self.conflict.pk, round_.pk]),
            {"direction": "not_handed_over"},
        )
        self.assertEqual(resp.status_code, 302)

    def test_view_party_can_see_detail_non_staff_blocked_from_list(self):
        self._start_conflict()
        buyer_client = Client()
        buyer_client.force_login(self.buyer)
        resp = buyer_client.get(
            reverse("transfers:revocation_conflict_detail", args=[self.conflict.pk])
        )
        self.assertEqual(resp.status_code, 200)
        resp = buyer_client.get(reverse("transfers:admin_revocation_conflicts"))
        self.assertEqual(resp.status_code, 403)
