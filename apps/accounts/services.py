"""账号与校内认证服务（A 包）。

共同开发约定 M0 接口：
    is_verified(*, user_id) -> bool
仅表示当前校内认证资格，不表示借用资格（借用限制由 C 的 can_borrow 判断）。
"""

from .models import IdentityApplication


def is_verified(*, user_id: int) -> bool:
    """当前校内认证资格：最新一条身份申请已通过且未被撤销。"""
    latest = IdentityApplication.objects.filter(user_id=user_id).first()
    if latest is None:
        return False
    return latest.status == IdentityApplication.Status.APPROVED
