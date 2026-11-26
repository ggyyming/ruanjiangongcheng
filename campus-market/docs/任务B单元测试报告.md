# 任务 B 单元测试报告

> 测试对象：**任务 B（流转交易与模拟资金）** —— `apps/transfers/` + `apps/payments/`
> 测试用例来源：GitHub 仓库 `ggyyming/ruanjiangongcheng`（`main` 分支）中的测试代码

## 1. 测试概述

- **被测模块**：流转交易（申请、预留、交付确认、取消、撤销、撤销去向分歧）与模拟资金（发起支付、模拟回执、退款、对账重试）。
- **用例来源**：仓库内已有的测试用例，共 **43 个**，分布在 3 个测试文件：
  | 测试文件 | 用例数 | 覆盖内容 |
  |---|---|---|
  | `apps/transfers/tests/test_services.py` | 21 | 申请 / 预留 / 交付确认 / 取消 / 撤销 |
  | `apps/transfers/tests/test_revocation_conflict.py` | 11 | 撤销去向分歧（管理员接单、双确认、轮次、补建） |
  | `apps/payments/tests/test_services.py` | 11 | 发起支付、模拟回执、退款、对账重试 |
- **测试类型说明**：用例基于 Django `TestCase`（真实测试数据库 + ORM），属**服务层测试**（service-layer test），覆盖业务规则与跨包依赖（A/C/Loans）以 `@patch` 打桩隔离，验证 B 模块自身逻辑。严格意义上的「单元测试」（无数据库）仅用于健康检查，本次任务 B 的 43 例均为服务层测试。
- **测试脚本**：`run_task_b_tests.bat`（见第 3 节）。

## 2. 测试环境

| 项目 | 版本 / 值 |
|---|---|
| 操作系统 | Windows 11 |
| Python | 3.13.15 |
| Django | 5.2.17 |
| 数据库（测试） | SQLite 内存库（`file:memorydb_default?mode=memory&cache=shared`） |
| 依赖管理 | uv |
| 测试命令 | `uv run python manage.py test apps.transfers apps.payments -v 2` |

## 3. 测试脚本

脚本文件：`run_task_b_tests.bat`（仓库根目录 `campus-market/` 下），双击或命令行运行均可一键复现：

```bat
@echo off
chcp 65001 >nul
cd /d "%~dp0"
uv run python manage.py test apps.transfers apps.payments -v 2
echo Exit code: %ERRORLEVEL%
```

在项目目录下等价命令：

```bash
uv run python manage.py test apps.transfers apps.payments -v 2
```

## 4. 单元测试用例表（43 例）

> 预期结果 = 该用例声明的业务行为；实际结果 = 本次运行后断言成立时的具体返回值/状态值。43 例均通过，实际结果与预期逐项一致。

### 4.1 流转交易 —— `test_services.py`（21 例）

| 序号 | 用例名 | 所属测试类 | 预期结果 | 实际结果 |
|---|---|---|---|---|
| 1 | test_apply_creates_pending_application | ApplyTests | 已实名认证买家申请物品，生成 `PENDING` 且 `kind=SALE` 的申请 | `app.status = PENDING`、`app.kind = SALE` |
| 2 | test_unverified_apply_rejected | ApplyTests | 未实名认证用户申请被拒，且不落库 | 抛 `PermissionDenied`，`Application.objects.count() = 0` |
| 3 | test_apply_own_item_rejected | ApplyTests | 申请自己发布的物品被拒 | 抛 `ValidationError` |
| 4 | test_duplicate_pending_apply_rejected | ApplyTests | 重复提交待处理申请被拒 | 第二次申请抛 `ValidationError` |
| 5 | test_reserve_selects_one_and_closes_others | ReserveTests | 选中 app1、关闭 app2，生成 `RESERVED` 流转且金额正确 | `app1 = SELECTED`、`app2 = CLOSED`、`transfer = RESERVED`、`amount = 10.00` |
| 6 | test_non_owner_cannot_reserve | ReserveTests | 非物品所有者预留被拒 | 抛 `PermissionDenied` |
| 7 | test_reserve_already_handled_rejected | ReserveTests | 对已处理申请再次预留被拒 | 抛 `ValidationError` |
| 8 | test_reserve_twice_on_same_item_rejected | ReserveTests | 同一物品第二笔（已关闭）申请预留被拒 | 抛 `ValidationError` |
| 9 | test_unique_active_transfer_per_item | ReserveTests | 同一物品创建第二笔进行中流转触发唯一约束 | 抛 `IntegrityError` |
| 10 | test_sale_confirm_requires_payment | ConfirmDeliveryTests | 未付款即确认交付被拒 | 抛 `ValidationError` |
| 11 | test_single_confirmation_does_not_complete | ConfirmDeliveryTests | 单方确认不完成流转、不触发结算 | `owner_confirmed_at ≠ None`、`recipient_confirmed_at = None`、`status = RESERVED`、结算未调用 |
| 12 | test_both_confirm_completes_and_settles | ConfirmDeliveryTests | 双方确认后流转完成并触发一次结算 | `status = COMPLETED`，`initiate_settlement` 调用 1 次 |
| 13 | test_cannot_confirm_for_other_party | ConfirmDeliveryTests | 无关第三方确认被拒 | 抛 `PermissionDenied` |
| 14 | test_repeat_confirm_idempotent | ConfirmDeliveryTests | 重复确认幂等，确认时间不变 | 二次确认后 `owner_confirmed_at` 与首次相等 |
| 15 | test_cancel_before_delivery | CancelTests | 交付前取消，流转与申请均取消 | `transfer = CANCELLED`、`app = CANCELLED` |
| 16 | test_cancel_requires_reason | CancelTests | 无原因取消被拒 | 空原因抛 `ValidationError` |
| 17 | test_cancel_after_one_confirmed_rejected | CancelTests | 一方已确认后单方取消被拒 | 抛 `ValidationError` |
| 18 | test_start_revoke_requires_one_confirmation | RevokeTests | 双方均未确认即发起撤销被拒 | 抛 `ValidationError` |
| 19 | test_start_revoke_after_one_confirmed | RevokeTests | 一方确认后发起撤销，进入协商，发起方为接收方 | `revoke_status = NEGOTIATING`、`initiator = RECIPIENT`、`recipient_agreed_at ≠ None` |
| 20 | test_revoke_completes_when_both_declare_and_agree | RevokeTests | 双方声明未交付并同意后撤销完成、恢复可用 | `status = REVOKED`、`revoke_status = REVOKED`、`change_availability` 调用 1 次 |
| 21 | test_revoke_withdraw_restores | RevokeTests | 双方撤回后恢复原状态 | `revoke_status = NONE`、`status = RESERVED` |

### 4.2 撤销去向分歧 —— `test_revocation_conflict.py`（11 例）

| 序号 | 用例名 | 所属测试类 | 预期结果 | 实际结果 |
|---|---|---|---|---|
| 22 | test_b1_conflict_created_no_refund | RevocationConflictTestCase | 去向分歧建立冲突记录且不退款 | `conflict = OPEN`、`transfer = RESERVED`、`revoke_status = NEGOTIATING`，`request_refund` 未调用 |
| 23 | test_b1_conflict_appears_in_pending_once | RevocationConflictTestCase | 冲突在待认领列表出现且仅一次 | 待认领列表 = `[conflict.pk]` |
| 24 | test_b2_only_one_admin_claims | RevocationConflictTestCase | 仅一名管理员可认领，重复认领幂等 | 认领人 `= admin`、`status = IN_PROGRESS`；admin2 认领抛 `ValidationError`；admin 重复认领仍为本人 |
| 25 | test_b2_non_staff_cannot_claim | RevocationConflictTestCase | 非管理员认领被拒 | 抛 `PermissionDenied` |
| 26 | test_b3_round_double_confirm_completes_with_single_refund | RevocationConflictTestCase | 单方提交不足以撤销，双方一致后撤销且仅退款一次 | 单方后 `status = RESERVED`、未退款；双方一致后 `status = REVOKED`、`conflict = RESOLVED`、退款 1 次、恢复可用 1 次 |
| 27 | test_b4_stale_round_rejected | RevocationConflictTestCase | 旧轮次提交被拒，本轮双方一致完成撤销 | 第 1 轮 `result = CONFLICT`；旧轮提交抛 `ValidationError`；第 2 轮双方一致后 `status = REVOKED` |
| 28 | test_b5_withdraw_after_claim_closes_entry | RevocationConflictTestCase | 认领后双方撤回，冲突关闭且旧链接失效 | `revoke_status = NONE`、`conflict = CLOSED`；旧轮声明抛 `ValidationError` |
| 29 | test_b6_backfill_picks_up_old_conflicting_records | RevocationConflictTestCase | 补建历史冲突记录并可认领 | 补建 `= 1` 条、待认领 `= 1` 条、认领后 `status = IN_PROGRESS` |
| 30 | test_round_declare_idempotent_no_overwrite | RevocationConflictTestCase | 重复声明幂等，不覆盖已确认去向 | `owner_direction = "not_handed_over"`（未被二次提交覆盖） |
| 31 | test_view_admin_claim_round_flow | RevocationConflictTestCase | 管理员认领/轮次/详情路由接线正确、模板渲染正常 | 列表 `200` 且含「撤销去向分歧」；认领 `302` 重定向；详情 `200`；发起轮次与声明均 `302` |
| 32 | test_view_party_can_see_detail_non_staff_blocked_from_list | RevocationConflictTestCase | 当事人可看详情，非管理员访问列表被拒 | 当事人详情 `200`；非管理员访问列表 `403` |

### 4.3 模拟资金 —— `test_services.py`（11 例）

| 序号 | 用例名 | 所属测试类 | 预期结果 | 实际结果 |
|---|---|---|---|---|
| 33 | test_payment_starts_processing_not_paid | RequestPaymentTests | 发起支付后进入处理中，尚未到账 | `op.status = PAYING`、`is_paid() = False` |
| 34 | test_donation_has_no_payment | RequestPaymentTests | 捐赠类型无支付环节 | 抛 `ValidationError` |
| 35 | test_receipt_success_marks_paid | SimulatedReceiptTests | 回执成功标记到账 | `op.status = PAID`、`is_paid() = True` |
| 36 | test_receipt_failure_not_paid | SimulatedReceiptTests | 回执失败标记失败，未到账 | `op.status = PAY_FAILED`、`is_paid() = False` |
| 37 | test_processing_not_counted_as_paid | SimulatedReceiptTests | 处理中不算作到账 | `is_paid() = False` |
| 38 | test_duplicate_receipt_does_not_regress | SimulatedReceiptTests | 重复回执不回退已到账状态 | 第二次回执（failure）后 `op.status` 仍为 `PAID` |
| 39 | test_refund_retry_max_then_manual | RetryTests | 失败超重试上限转人工，人工关闭幂等，再次退款复用同一操作 | `status = NEEDS_MANUAL`、`attempts = 3`；重复人工登记抛 `ValidationError`；再次退款返回同一操作且 `status = MANUAL_CLOSED`、`manual_note = "待核实"`、`reason = "测试退款"` |
| 40 | test_unknown_not_blindly_retried | RetryTests | 回执 unknown 不盲目重试，转入待对账 | 返回 `"needs_reconcile"`、`status = UNKNOWN`、`attempts = 0` |
| 41 | test_refund_requires_cancelled_for_sale | RequestRefundTests | 买卖未取消/撤销时退款被拒 | 抛 `ValidationError` |
| 42 | test_refund_blocked_by_open_dispute | RequestRefundTests | 存在未结争议时退款被拒 | 抛 `ValidationError` |
| 43 | test_refund_idempotent | RequestRefundTests | 重复退款幂等，仅一条退款操作 | 两次退款返回同一 `op.id`，退款记录 `count = 1` |

## 5. 测试结果汇总

执行命令：

```bash
uv run python manage.py test apps.transfers apps.payments -v 2
```

运行输出摘要：

```
Ran 43 tests in 0.513s
OK
```

| 统计项 | 数量 |
|---|---|
| 用例总数 | 43 |
| 通过 | 43 |
| 失败 | 0 |
| 错误 | 0 |
| 通过率 | 100% |
| 运行耗时 | 0.513s |

- **预期结果**：43 个用例各自声明的断言（状态字段、异常类型、调用次数、幂等性）全部成立，逐项见第 4 节。
- **实际结果**：43 个用例断言逐项成立，各字段实际值、抛错类型、调用次数均与预期一致（见第 4 节「实际结果」列），0 失败、0 错误，与预期完全一致。

## 6. 结论

任务 B（流转交易与模拟资金）共 43 个服务层测试用例，覆盖申请、预留、交付双确认、取消、撤销、撤销去向分歧（管理员接单、双确认轮次）、模拟支付回执、退款与对账重试等核心业务规则。本次运行 **43 例全部通过，无失败、无错误**，每项用例的实际结果与其预期结果一致。
