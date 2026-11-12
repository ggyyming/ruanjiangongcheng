# 交接记录 CAMPUS-B（流转交易与模拟资金）

- 任务：CAMPUS-B
- 分支：`codex/b-m0`（尚未提交；基线 SHA = `4b2b135`，交付 SHA 待提交后补）
- 实现范围：CP-R-01/02/09~13/19~25；重点 CP-D-08/09/13/17/18、CP-ST-03~17/20~24/34/37/38、CP-BR-06~10/17~24
- 未完成项：迁移未生成（等 A0 的 `apps.catalog` 落地）；Django Admin 未注册（涉及对象/字段授权，需按约定 §4 单独做）；公共导航与 base.html 依赖 A

## 模型与迁移

- `apps/transfers/models.py`：`Application`（kind/status，`UniqueConstraint` 同一物品同一申请人仅一条待选择）、`Transfer`（kind/status/revoke_status、金额预留时固化、`owner_confirmed_at`/`recipient_confirmed_at` 独立记录、`UniqueConstraint` 同一物品同时最多一笔进行中流转）、`Revocation`（协商撤销双方声明/同意/撤回记录）、`TransferLog`（审计）
- `apps/payments/models.py`：`PaymentOperation`（kind=支付/结算/退款，purpose=货款/押金，`business_id` 唯一防重复）
- 金额统一 `DecimalField`；时间 `USE_TZ=True` + `Asia/Shanghai`，均 timezone-aware
- 迁移由模型所属成员生成：A0 落地后执行 `uv run python manage.py makemigrations transfers payments`

## 接口（apps.<app>.services，统一关键字参数）

B 对外（A/C 依赖）：

- `transfers.services.active_transfer_for_item(*, item_id)` → Transfer|None（A 查进行中流转）
- `transfers.services.close_pending_loan_applications(*, user_id, reason)` → int（C 逾期限制触发）
- `payments.services.is_paid(*, transfer_id, purpose)` → bool
- `payments.services.request_refund(*, transfer_id, reason)` → PaymentOperation（幂等）

B 内部主要服务（页面调用）：

- `apply(*, actor, item_id)` / `reserve(*, actor, application_id)` / `confirm_delivery(*, actor, transfer_id)` / `cancel_before_delivery(*, actor, transfer_id, reason)`
- `start_revoke` / `declare_direction` / `agree_revoke` / `withdraw_revoke`（均 `(*, actor, transfer_id, ...)`）
- `request_payment(*, transfer_id, purpose, amount=None)` / `pay_transfer(*, actor, transfer_id)` / `initiate_settlement(*, transfer_id)` / `apply_simulated_receipt(*, operation_id, result)` / `reconcile_and_retry(op)`

B 对 A 的依赖（函数体内惰性导入）：

- `accounts.services.is_verified(*, user_id)`；`catalog.services.can_display(*, item_id)`；`catalog.services.change_availability(*, item_id, available, reason)`
- 假定 `catalog.Item` 字段：`owner`、`kind`(sale/donation/borrow)、`price`、`deposit`、`name`（集中在 `transfers/services.py::_item_kind`/`_fixed_amount`，字段名对齐后只改这两处）

B 对 C 的依赖：`loans.services.can_borrow`/`delivery_ready`/`start_loan`、`disputes.services.has_open_dispute`、`notifications.services.notify`

## 资金模拟

- 只由受控管理命令产生回执；普通用户页面只能“发起（模拟）付款”，不能直接写到账
- `simulate_receipt --operation-id <id> --result success|failure|unknown`
- 演示失败/未知/重试：对某操作打 `failure` 后跑 `process_payment_operations`；打 `unknown` 表示先对账不盲重试

## 管理命令

- `process_payment_timeouts`：预留满 24h 且确认未付款才取消（CP-D-17）
- `process_payment_operations`：(1) 取消/撤销后迟到支付退款（有争议跳过）；(2) 失败/未知结算与退款对账+重试，最多 3 次不含首次，未知不盲重试，撤销/争议暂停
- 三条命令均可重复执行，按当前持久化数据判断

## 验证

- `uv run ruff check apps/transfers apps/payments config/urls.py` → All checks passed
- `uv run ruff format --check ...` → 已格式化
- `uv run python -m py_compile ...` → 通过
- `uv run python manage.py check` → 仅剩 4 条 E300/E307（`catalog.Item` 未安装，A0 未落地，预期）
- 单元测试 `apps/transfers/tests/test_services.py`、`apps/payments/tests/test_services.py` 已写但**暂不能运行**（`from apps.catalog.models import Item` 缺失）；A0 落地后运行 `uv run python manage.py test apps.transfers apps.payments`

## 接线与风险

- `config/urls.py` 已挂 `/transfers/`、`/payments/`；`config/settings.py` 已加 `apps.transfers`、`apps.payments`（含注释说明依赖 A0）
- 模板 `{% extends "base.html" %}`，base.html 由 A 维护；需要 A 提供菜单入口与 messages 展示
- 阻塞项：A0/C0 未落地 → 无法 `makemigrations`、无法跑测试、无法 `check` 全绿
