"""账号与校内认证服务（A 包）。

共同开发约定 M0 接口：
    is_verified(*, user_id) -> bool
仅表示当前校内认证资格，不表示借用资格（借用限制由 C 的 can_borrow 判断）。
"""
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from .models import IdentityApplication


def is_verified(*, user_id: int) -> bool:
    """当前校内认证资格：最新一条身份申请已通过且未被撤销。"""
    latest = IdentityApplication.objects.filter(user_id=user_id).first()
    if latest is None:
        return False
    return latest.status == IdentityApplication.Status.APPROVED


def submit_identity(*, user, name: str, staff_no: str, department: str) -> IdentityApplication:
    """提交或重新提交校内身份申请（CP-D-02：每次重新审核，历次结果保留）。"""
    if is_verified(user_id=user.id):
        raise ValidationError("校内身份已通过审核，无需重复提交")
    return IdentityApplication.objects.create(
        user=user, name=name, staff_no=staff_no, department=department
    )


def review_identity(
    *, actor, application_id: int, approve: bool, reason: str
) -> IdentityApplication:
    """管理员人工审核身份申请（CP-R-06）。驳回必须填写原因。"""
    if not actor.is_staff:
        raise PermissionDenied("仅管理员可审核校内身份")
    application = IdentityApplication.objects.filter(id=application_id).first()
    if application is None:
        raise ValidationError("身份申请不存在")
    if application.status != IdentityApplication.Status.PENDING:
        raise ValidationError("该申请已审核，请刷新后处理")
    if not approve and not reason:
        raise ValidationError("驳回时必须填写原因")
    application.status = (
        IdentityApplication.Status.APPROVED if approve else IdentityApplication.Status.REJECTED
    )
    application.review_reason = "" if approve else reason
    application.reviewed_by = actor
    application.reviewed_at = timezone.now()
    application.save()
    return application


def revoke_identity(*, actor, user_id: int, reason: str) -> IdentityApplication:
    """撤销校内认证（CP-D-04）：记录原因、下架未预留的公开物品、恢复须重新审核。

    ponytail: 通知双方依赖 C 的通知服务，M1 尚未接入，接入后在此追加 notify 调用。
    已预留/进行中流转的履约入口由 B 提供，本服务不取消任何流转。
    """
    if not actor.is_staff:
        raise PermissionDenied("仅管理员可撤销校内认证")
    if not reason:
        raise ValidationError("撤销认证必须填写原因")
    application = IdentityApplication.objects.filter(user_id=user_id).first()
    if application is None or application.status != IdentityApplication.Status.APPROVED:
        raise ValidationError("该用户当前没有有效的认证记录")
    application.status = IdentityApplication.Status.REVOKED
    application.review_reason = reason
    application.reviewed_by = actor
    application.reviewed_at = timezone.now()
    application.save()

    # CP-D-04：下架该用户未预留的公开物品。B 未提供预留事实前，
    # 只下架 display_status=可申请 的物品；预留关系的联动在 B0 合入后补充。
    from apps.catalog.models import Item  # 局部导入避免循环依赖
    from apps.catalog.services import change_availability

    for item in Item.objects.filter(owner_id=user_id, display_status=Item.DisplayStatus.AVAILABLE):
        # 严格按共同约定 M0 签名调用（item_id / available / reason）
        change_availability(item_id=item.id, available=False, reason=f"认证撤销：{reason}")
    return application
