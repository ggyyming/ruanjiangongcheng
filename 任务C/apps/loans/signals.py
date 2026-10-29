"""跨包集成信号。

本包不拥有资金记录、物品和流转申请，相关动作以信号交回对应包处理：

- ``deposit_refund_requested``：kwargs ``agreement``、``reason``。由流转/资金包
  据此创建退款记录并回写结果（C 不改资金记录）。
- ``borrow_ended``：kwargs ``agreement``、``outcome``（``returned`` /
  ``compensated`` / ``cancelled``）。由物品/流转包据此保持物品下架或更新状态。
- ``borrow_applications_should_close``：kwargs ``user``、``reason``。用于
  CP-D-21：受限用户的未选定借用申请由流转包关闭并记录原因。
"""

from django.dispatch import Signal

deposit_refund_requested = Signal()
borrow_ended = Signal()
borrow_applications_should_close = Signal()
