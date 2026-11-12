"""账号与校内认证服务（A 包）。

共同开发约定 M0 接口：
    is_verified(*, user_id) -> bool
仅表示当前校内认证资格，不表示借用资格（借用限制由 C 的 can_borrow 判断）。
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import IdentityApplication


def is_verified(*, user_id: int) -> bool:
    """当前校内认证资格：最新一条身份申请已通过且未被撤销。"""
    latest = IdentityApplication.objects.select_related("user").filter(user_id=user_id).first()
    if latest is None:
        return False
    return latest.status == IdentityApplication.Status.APPROVED and latest.user.is_active


@transaction.atomic
def submit_identity(*, user, name: str, staff_no: str, department: str) -> IdentityApplication:
    """提交或重新提交校内身份申请（CP-D-02：每次重新审核，历次结果保留）。"""
    get_user_model().objects.select_for_update().get(pk=user.pk)
    latest = user.identity_applications.first()
    if latest and latest.status == IdentityApplication.Status.APPROVED:
        raise ValidationError("校内身份已通过审核，无需重复提交")
    if latest and latest.status == IdentityApplication.Status.PENDING:
        raise ValidationError("已有一份身份申请正在审核，请等待审核结果。")
    return IdentityApplication.objects.create(
        user=user, name=name, staff_no=staff_no, department=department
    )


def claim_identity_review(*, actor, application_id: int) -> None:
    if not actor.is_staff:
        raise PermissionDenied("仅管理员可认领身份审核")
    claimed = IdentityApplication.objects.filter(
        pk=application_id, status=IdentityApplication.Status.PENDING, reviewed_by__isnull=True
    ).update(reviewed_by=actor)
    if not claimed:
        raise ValidationError("申请已被认领或审核，请刷新列表")


@transaction.atomic
def review_identity(
    *, actor, application_id: int, approve: bool, reason: str
) -> IdentityApplication:
    """管理员人工审核身份申请（CP-R-06）。驳回必须填写原因。"""
    if not actor.is_staff:
        raise PermissionDenied("仅管理员可审核校内身份")
    application = IdentityApplication.objects.select_for_update().filter(id=application_id).first()
    if application is None:
        raise ValidationError("身份申请不存在")
    if application.status != IdentityApplication.Status.PENDING:
        raise ValidationError("该申请已审核，请刷新后处理")
    if application.reviewed_by_id not in (None, actor.pk):
        raise PermissionDenied("只有负责管理员可以审核该申请")
    if not approve and not reason:
        raise ValidationError("驳回时必须填写原因")
    application.status = (
        IdentityApplication.Status.APPROVED if approve else IdentityApplication.Status.REJECTED
    )
    application.review_reason = "" if approve else reason
    application.reviewed_by = actor
    application.reviewed_at = timezone.now()
    application.save()
    from apps.loans.models import Notification
    from apps.loans.services import notify

    notify(
        application.user,
        business_kind=Notification.Business.IDENTITY,
        business_ref=application.pk,
        event="identity.reviewed",
        title=f"校内身份审核：{application.get_status_display()}",
    )
    return application


@transaction.atomic
def revoke_identity(*, actor, user_id: int, reason: str) -> IdentityApplication:
    """撤销校内认证，通知受影响的用户，已有流转继续履约。"""
    if not actor.is_staff:
        raise PermissionDenied("仅管理员可撤销校内认证")
    if not reason:
        raise ValidationError("撤销认证必须填写原因")
    application = IdentityApplication.objects.select_for_update().filter(user_id=user_id).first()
    if application is None or application.status != IdentityApplication.Status.APPROVED:
        raise ValidationError("该用户当前没有有效的认证记录")
    application.status = IdentityApplication.Status.REVOKED
    application.review_reason = reason
    application.reviewed_by = actor
    application.reviewed_at = timezone.now()
    application.save()

    from django.db.models import Q

    from apps.catalog.models import Item
    from apps.catalog.services import change_availability
    from apps.loans.models import Notification
    from apps.loans.services import notify, notify_transfer
    from apps.transfers.models import Transfer

    for item in Item.objects.filter(owner_id=user_id, display_status=Item.DisplayStatus.AVAILABLE):
        change_availability(item_id=item.id, available=False, reason="物主认证撤销")
    notify(
        application.user,
        business_kind=Notification.Business.IDENTITY,
        business_ref=application.pk,
        event="identity.revoked",
        title="校内认证已撤销",
    )
    for transfer in Transfer.objects.filter(
        Q(owner_id=user_id) | Q(recipient_id=user_id),
        status__in=(Transfer.Status.RESERVED, Transfer.Status.BORROWED),
    ).select_related("owner", "recipient"):
        notify_transfer(
            transfer,
            event="transfer.identity_revoked",
            title="一方校内认证已撤销，已有流转继续履约",
        )
    return application
