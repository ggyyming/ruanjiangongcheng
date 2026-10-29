"""物品市场服务（A 包）。

共同开发约定 M0 接口：
    can_display(*, item_id) -> bool
    change_availability(*, item_id, available, reason) -> Item
can_display 检查内容审核、下架和物主资格，不能据取消动作无条件公开；
change_availability 仅由获授权业务服务调用，available=True 仍校验公开条件，历史不改写。
"""

from django.core.exceptions import ValidationError

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
