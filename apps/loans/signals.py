"""跨包集成信号。

本包不拥有资金记录、物品和流转申请，相关动作以信号交回对应包处理：

- ``deposit_refund_requested``：kwargs ``agreement``、``reason``。由流转/资金包
  据此创建退款记录并回写结果（C 不改资金记录）。
- ``borrow_ended``：kwargs ``agreement``、``outcome``（``returned`` /
  ``compensated`` / ``cancelled``）。由物品/流转包据此保持物品下架或更新状态。
- ``borrow_applications_should_close``：kwargs ``user``、``reason``。用于
  CP-D-21：受限用户的未选定借用申请由流转包关闭并记录原因。
"""

from django.dispatch import Signal, receiver

deposit_refund_requested = Signal()
borrow_ended = Signal()
borrow_applications_should_close = Signal()


@receiver(deposit_refund_requested)
def request_refund_for_agreement(sender, *, agreement, reason, **kwargs):
    from apps.payments.services import request_refund

    request_refund(transfer_id=agreement.transfer_id, reason=reason)


@receiver(borrow_ended)
def finish_borrowed_transfer(sender, *, agreement, outcome, **kwargs):
    from apps.transfers.services import end_borrowed_transfer

    if outcome in ("returned", "compensated"):
        end_borrowed_transfer(transfer_id=agreement.transfer_id)


@receiver(borrow_applications_should_close)
def close_pending_applications(sender, *, user, reason, **kwargs):
    from apps.transfers.services import close_pending_loan_applications

    close_pending_loan_applications(user_id=user.pk, reason=reason)
