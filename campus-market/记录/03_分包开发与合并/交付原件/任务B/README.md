# 任务 B：流转交易与模拟资金 —— 交付整理

本目录是 B 包（`apps/transfers/` + `apps/payments/`）的**交付副本**，供集成者 / 其他 AI 阅读。
源码仍以仓库内 `apps/` 下为准；本目录只是把 B 写的代码 + 接线整理到一起，方便合并。

> 依赖 A0（`apps.catalog` / `apps.accounts`）与 C0（`apps.loans` / `apps.disputes` / `apps.notifications`）。
> 由于 A/C 尚未落地，本包使用字符串外键 `"catalog.Item"` 与函数体内惰性导入，见「接线」一节。

---

## 1. 目录结构

```
任务B/
├── README.md                 # 本说明
├── config/
│   └── urls.py               # 挂载 /transfers/、/payments/（含 include）
└── apps/
    ├── transfers/            # 申请、预留、双确认、取消、协商撤销
    │   ├── models.py         # Application / Transfer / Revocation / TransferLog
    │   ├── services.py       # 全部状态变更的服务层（视图不得直接改状态）
    │   ├── forms.py          # ReasonForm / DirectionForm（只承载输入）
    │   ├── views.py          # /transfers/ 页面
    │   ├── urls.py           # namespace "transfers"
    │   ├── templates/transfers/*.html
    │   └── tests/test_services.py
    └── payments/             # 模拟支付 / 结算 / 退款
        ├── models.py         # PaymentOperation
        ├── services.py       # 资金状态机 + 受控模拟回执
        ├── views.py          # /payments/ 页面
        ├── urls.py           # namespace "payments"
        ├── management/commands/   # 3 条管理命令
        │   ├── process_payment_timeouts.py
        │   ├── process_payment_operations.py
        │   └── simulate_receipt.py
        ├── templates/payments/*.html
        └── tests/test_services.py
```

## 2. 状态口径（与状态转换说明一一对应）

- Application：`待选择 -> 已选中 | 已关闭 | 已取消`（CP-ST-03/04/13）
- Transfer：`已预留 -> 已成交(买卖) | 赠送完成 | 已借出(借用) | 已撤销 | 已取消`（CP-ST-04/06/10/13/17）
- Revocation（协商撤销）：`none -> 撤销协商中 -> 已撤销`；双方撤回后恢复 `none`（CP-ST-16/17/34）
- PaymentOperation 三类处理，各自独立状态：
  - 支付：`未支付 -> 支付处理中 -> 已支付 | 支付失败 | 结果未知`
  - 结算：`未发起结算 -> 结算处理中 -> 已结算到账 | 结算失败 | 结果未知`
  - 退款：`未发起退款 -> 退款处理中 -> 已退款到账 | 退款失败 | 结果未知`
  - 附加：`转人工处理`（重试达上限）

关键业务规则（对应细则）：CP-D-08 每次借用必收押金；CP-D-09 退款失败先对账、最多自动重试 3 次不含首次、转人工；CP-D-13 撤销协商中暂停交付确认/发起结算/付款，撤回后恢复；CP-D-17 预留 24h 未付、确认未付才取消、迟到支付退款；CP-D-18 结算失败重试、撤销/争议暂停。

## 3. 服务接口（`apps.<app>.services`，统一关键字参数）

B 对 A / C 提供的对外接口：

| 接口 | 返回 | 说明 |
|---|---|---|
| `transfers.services.active_transfer_for_item(*, item_id)` | Transfer\|None | A 查物品当前进行中流转（已预留/已借出） |
| `transfers.services.close_pending_loan_applications(*, user_id, reason)` | int | C 逾期限制触发，仅关未选定借用申请 |
| `payments.services.is_paid(*, transfer_id, purpose)` | bool | 依据持久化成功结果判断，不信任浏览器声明 |
| `payments.services.request_refund(*, transfer_id, reason)` | PaymentOperation | 幂等，服务内复核业务资格 |

B 内部主要服务（页面调用）：`apply` / `reserve` / `confirm_delivery` / `cancel_before_delivery` / `start_revoke` / `declare_direction` / `agree_revoke` / `withdraw_revoke`；`request_payment` / `pay_transfer` / `initiate_settlement` / `apply_simulated_receipt` / `reconcile_and_retry`。

B 依赖 A：`accounts.services.is_verified(*, user_id)`、`catalog.services.can_display(*, item_id)`、`catalog.services.change_availability(*, item_id, available, reason)`；假定 `Item` 字段 `owner` / `kind`(sale/donation/borrow) / `price` / `deposit` / `name`（集中在 `transfers/services.py` 的 `_item_kind` / `_fixed_amount`，字段名对齐后只改这两处）。

B 依赖 C：`loans.services.can_borrow` / `delivery_ready` / `start_loan`、`disputes.services.has_open_dispute`、`notifications.services.notify`。

## 4. 管理命令

| 命令 | 职责 |
|---|---|
| `process_payment_timeouts` | 预留满 24h 的买卖/借用，确认未付（未发起/支付失败）才取消；已付保留；处理中/未知先对账不取消；赠送不适用 |
| `process_payment_operations` | (1) 取消/撤销后迟到支付退款（有争议跳过）；(2) 失败/未知结算与退款对账 + 重试（最多 3 次不含首次，未知不盲重试，撤销/争议暂停） |
| `simulate_receipt --operation-id <id> --result success\|failure\|unknown` | 受控模拟第三方回执，普通用户无页面入口 |

三条命令均可重复执行，按当前持久化状态判断，不重复处理。

## 5. 接线（集成时必做）

1. `config/settings.py` 的 `INSTALLED_APPS` 增加：
   ```python
   "apps.transfers",
   "apps.payments",
   ```
   （源仓库 settings.py 已加，本目录未复制 settings.py，只在此说明改动点。）
2. `config/urls.py` 增加（本目录 `config/urls.py` 已是完整版本）：
   ```python
   path("transfers/", include("apps.transfers.urls")),
   path("payments/", include("apps.payments.urls")),
   ```
3. 模板统一 `{% extends "base.html" %}`，`base.html` 与公共导航由 A 维护；需 A 提供“我的申请 / 我的流转”菜单入口与 messages 展示。
4. A0 落地后生成迁移：`uv run python manage.py makemigrations transfers payments`。

## 6. 验证结果

- `uv run ruff check apps/transfers apps/payments config/urls.py` → All checks passed
- `uv run ruff format --check ...` → 已格式化
- `uv run python -m py_compile ...` → 通过
- `uv run python manage.py check` → 仅剩 4 条 E300/E307（`catalog.Item` 未安装，A0 未落地，预期）
- 单元测试已写但**暂不能运行**（`from apps.catalog.models import Item` 缺失）；A0 落地后 `uv run python manage.py test apps.transfers apps.payments`

## 7. 阻塞项 / 风险

- A0/C0 未落地：无法 `makemigrations`、无法跑测试、无法 `check` 全绿。
- Django Admin 未注册 B 模型：涉及对象/字段级授权（共同约定 §4），不建议默认注册敏感模型，留待集成者统一处理。
- 借用押金金额：初始以 `Item.deposit` 展示值固化，最终以 C 双方约定为准（`request_payment(amount=...)` 可覆盖），需与 C 联调对齐。
