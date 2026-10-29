"""物品市场服务（A 包）。

共同开发约定 M0 接口：
    can_display(*, item_id) -> bool
    change_availability(*, item_id, available, reason) -> Item
can_display 检查内容审核、下架和物主资格，不能据取消动作无条件公开；
change_availability 仅由获授权业务服务调用，available=True 仍校验公开条件，历史不改写。
"""
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.accounts.services import is_verified

from .models import Item, ItemAvailabilityChange


def can_display(*, item_id: int) -> bool:
    """物品当前是否满足公开展示条件：内容审核通过（可申请）且物主具备校内认证资格。"""
    item = Item.objects.filter(id=item_id).first()
    if item is None:
        return False
    if item.display_status != Item.DisplayStatus.AVAILABLE:
        return False
    return is_verified(user_id=item.owner_id)


def change_availability(*, item_id: int, available: bool, reason: str) -> Item:
    """变更物品公开资格，只写状态变更记录，不改写历史。

    - available=True：恢复为"可申请"，但仍校验公开条件（物主须有校内认证资格）。
    - available=False：下架，须记录原因。
    """
    if not reason:
        raise ValidationError("变更公开资格必须填写原因")
    item = Item.objects.filter(id=item_id).first()
    if item is None:
        raise ValidationError("物品不存在")
    if available:
        if item.display_status not in (
            Item.DisplayStatus.REJECTED,
            Item.DisplayStatus.OFFLINE,
        ):
            raise ValidationError("仅已驳回或已下架的物品可恢复公开")
        if not is_verified(user_id=item.owner_id):
            raise ValidationError("物主已不具备校内认证资格，不能恢复公开")
        item.display_status = Item.DisplayStatus.AVAILABLE
    else:
        item.display_status = Item.DisplayStatus.OFFLINE
    item.save(update_fields=["display_status"])
    ItemAvailabilityChange.objects.create(
        item=item, available=available, reason=reason, changed_by=None
    )
    return item


def create_item(*, owner, **fields) -> Item:
    """发布物品（CP-R-07/08）：须已通过校内认证，创建后进入待审核。"""
    if not is_verified(user_id=owner.id):
        raise PermissionDenied("须通过校内身份审核后才能发布物品")
    return Item.objects.create(owner=owner, display_status=Item.DisplayStatus.PENDING, **fields)


def edit_item(*, owner, item_id: int, **fields) -> Item:
    """修改物品（CP-D-10）：仅物主；修改后转待审核，审核通过前隐藏。

    ponytail: 有进行中流转时禁止修改的规则依赖 B 的流转事实接口，
    B0 合入后在此接入查询并拒绝。
    """
    item = Item.objects.filter(id=item_id).first()
    if item is None:
        raise ValidationError("物品不存在")
    if item.owner_id != owner.id:
        raise PermissionDenied("只能修改本人发布的物品")
    for key, value in fields.items():
        setattr(item, key, value)
    item.display_status = Item.DisplayStatus.PENDING
    item.save()
    return item


def review_item(*, actor, item_id: int, approve: bool, reason: str) -> Item:
    """管理员审核物品内容（CP-R-08/CP-D-05）：通过后公开，驳回须记录原因。

    通过时仍校验物主资格：物主已不具备校内认证则不公开，保留待审核。
    """
    if not actor.is_staff:
        raise PermissionDenied("仅管理员可审核物品内容")
    item = Item.objects.filter(id=item_id).first()
    if item is None:
        raise ValidationError("物品不存在")
    if item.display_status != Item.DisplayStatus.PENDING:
        raise ValidationError("该物品不在待审核状态")
    if not approve and not reason:
        raise ValidationError("驳回时必须填写原因")
    item.reviewed_by = actor
    item.reviewed_at = timezone.now()
    if approve:
        item.review_reason = ""
        if is_verified(user_id=item.owner_id):
            item.display_status = Item.DisplayStatus.AVAILABLE
        else:
            item.display_status = Item.DisplayStatus.PENDING
            item.review_reason = "物主认证状态异常，暂不公开"
    else:
        item.display_status = Item.DisplayStatus.REJECTED
        item.review_reason = reason
    item.save()
    return item


def offline_item(*, owner, item_id: int, reason: str = "物主下架") -> Item:
    """物主下架物品（可申请 → 已下架）。"""
    item = Item.objects.filter(id=item_id).first()
    if item is None:
        raise ValidationError("物品不存在")
    if item.owner_id != owner.id:
        raise PermissionDenied("只能下架本人发布的物品")
    return change_availability(item_id=item.id, available=False, reason=reason)


def relist_item(*, owner, item_id: int) -> Item:
    """物主申请重新上架（CP-D-11）：已下架 → 待审核，重新审核通过后才开放。"""
    item = Item.objects.filter(id=item_id).first()
    if item is None:
        raise ValidationError("物品不存在")
    if item.owner_id != owner.id:
        raise PermissionDenied("只能重新上架本人发布的物品")
    if item.display_status != Item.DisplayStatus.OFFLINE:
        raise ValidationError("仅已下架的物品可申请重新上架")
    item.display_status = Item.DisplayStatus.PENDING
    item.save(update_fields=["display_status"])
    return item
