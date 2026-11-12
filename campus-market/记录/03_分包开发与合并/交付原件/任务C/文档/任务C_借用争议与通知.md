# 任务 C：借用争议与通知（实现与交接说明）

版本：1.0；实现日期：2026-10-29；范围：校园物品流转平台业务包 C。

本文件说明本包已实现的内容、运行方式、与 A/B 两个业务包的接口，以及**尚未验证**的边界。它不是最终项目验收记录；最终验收由集成者在三包合并后执行。

本文件随独立交付包提供：应用位于 `任务C/apps/loans/`，整合后为 `apps/loans/`；整合步骤见 `任务C/README.md`。

## 1. 实现范围

本包对应需求文档中的借用、归还、延期、逾期与争议规则：

| 需求 | 实现位置 | 说明 |
|---|---|---|
| CP-R-03 借用 | `BorrowAgreement`、`create_agreement()`、`start_borrow()` | 借用申请、预留、交付由 B 包完成；本包记录借用全生命周期 |
| CP-R-04 归还 | `confirm_return()` | 借用者交还、物主收回双确认后才为已归还 |
| CP-R-14 归还期限 | `set_due_date()`、`confirm_due_date()` | 双方分别确认同一日期时间，交付前完成 |
| CP-R-15 归还双确认 | `confirm_return()` | 单方确认不结束借用 |
| CP-R-16 逾期提醒与限制 | `scan_overdue()`、`BorrowRestriction`、`Notification` | 标记逾期、站内提醒双方、限制借用者新增借用 |
| CP-R-17 全部结束后恢复 | `release_restrictions_for()` | 全部逾期借用已归还或赔偿结清且争议关闭后才解除 |
| CP-R-18 延期 | `request_extension()`、`decide_extension()` | 到期前申请；允许到期后批准；历史保留 |
| CP-R-26 损坏/丢失争议 | `open_dispute()`、`record_plan()`、`confirm_plan_performed()`、`agree_dispute_end()` | 方案、履行、结束意见、关闭分别记录 |
| CP-R-27 丢失赔偿结清 | 争议关闭后的 `COMPENSATED` 状态 | 不写为已归还，纳入资格恢复条件 |

对应细则：CP-D-06（北京时间）、CP-D-07（跨期批准）、CP-D-11（归还后不自动开放，由物品包处理）、CP-D-12（履行与关闭）、CP-D-14（损坏争议阻断归还）、CP-D-15/16（押金退款条件）、CP-D-19（延期不限次数）、CP-D-20（仅站内通知）、CP-D-21（关闭未选定借用申请）、CP-D-22（争议材料权限）。

状态转换：CP-ST-09 至 12、19、25 至 29、31、35、36。

**押金支付与退款不在本包**：本包只保存约定押金金额、在符合条件时通过信号请求全额原路退款，不创建资金记录、不判断到账。

## 2. 运行方式

```bash
uv sync
uv run python manage.py migrate
uv run python manage.py check
uv run python manage.py test
uv run python manage.py runserver
```

- 借用页面：`http://127.0.0.1:8000/loans/`（未登录会跳转到 `/admin/login/`）。
- Django 管理后台：`http://127.0.0.1:8000/admin/`，可创建用户、借用约定、延期和争议。
- 逾期扫描：`uv run python manage.py scan_overdue_loans`。项目未引入 Celery/Redis，需由系统计划任务（如 Windows 任务计划、cron）定期执行；重复执行不会重复标记或重复限制。
- 时区：数据库存 UTC，页面和业务提示按 `Asia/Shanghai`（北京时间）显示，符合 CP-D-06。

### 手工验证路径

1. 在后台创建物主、借用者两个用户，以及一条“待交付”借用约定（押金大于 0）。
2. 物主登录 `/loans/`，提出归还时间；借用者确认同一时间。
3. 在后台把该约定改为“借用中”（或由 B 包调用 `start_borrow()` 后进入）。
4. 借用者确认交还 → 仍为“待另一方归还确认”；物主确认收回 → “已归还”，并发出押金退款信号。
5. 另建一条已逾期约定，运行 `scan_overdue_loans`，确认双方收到站内通知、借用者出现限制。
6. 提交争议：记录方案 → 双方分别确认已履行 → 双方同意结束 → 系统关闭；丢失争议关闭后状态为“赔偿结清”，不是“已归还”。

## 3. 与 A/B 包的集成接口

本包不导入 A/B 的模型，也不自建用户系统。用户外键使用 `settings.AUTH_USER_MODEL`；物品和流转申请以字符串标识加物品名称快照保存。合并时按“共同开发约定”替换为外键即可，页面和规则逻辑不变。

### 3.1 B 包调用本包

```python
from apps.loans import services

# 物主选定借用申请人、创建预留后
agreement = services.create_agreement(
    owner=item.owner,
    borrower=application.applicant,
    item_ref=str(item.pk),
    item_title=item.name,
    deposit_amount=agreed_amount,
    application_ref=str(application.pk),
)

# 交付双确认且押金支付成功后
services.start_borrow(agreement)

# 交付前取消
services.cancel_unstarted_agreement(agreement, reason)

# 创建借用申请前检查资格
services.is_borrow_restricted(user)

# 判断资金/交付条件时
agreement.has_open_dispute()
```

- 本包**不校验押金是否已支付**；B 包必须只在支付成功后调用 `start_borrow()`。
- `create_agreement()` 时借用进入“待交付”；B 包负责申请、预留、交付确认和资金。

### 3.2 本包向 B/A 发出信号（`apps.loans.signals`）

| 信号 | 参数 | 由谁处理 | 用途 |
|---|---|---|---|
| `deposit_refund_requested` | `agreement`、`reason` | B（资金） | 创建全额原路退款记录并回写结果；同一借用只发一次 |
| `borrow_ended` | `agreement`、`outcome`（`returned`/`compensated`/`cancelled`） | A/B（物品、流转） | 保持物品下架；归还或赔偿结清后不自动重新开放（CP-D-11） |
| `borrow_applications_should_close` | `user`、`reason` | B（申请） | CP-D-21：关闭该用户尚未被选定的借用申请 |

示例接收器：

```python
from django.dispatch import receiver
from apps.loans.signals import deposit_refund_requested

@receiver(deposit_refund_requested)
def create_refund(sender, agreement, reason, **kwargs):
    ...
```

### 3.3 站内通知供所有包使用

```python
from apps.loans.services import notify
from apps.loans.models import Notification

notify(
    user,
    business_kind=Notification.Business.IDENTITY,
    business_ref=application.pk,
    event="identity.approved",
    title="校内身份审核已通过",
    body="你现在可以发布物品和申请流转。",
)
```

通知只记录发送时间与已读时间；送达或已读不替代交付、归还或资金结果确认（CP-D-20）。

## 4. 关键实现决策与假设

1. **跨包依赖**：仓库底座没有 A/B 包，因此本包以 `AUTH_USER_MODEL` + 物品标识/名称快照运行，并用信号向 B 发起资金与申请关闭动作。集成时把 `item_ref`/`application_ref` 换成外键，并接入信号接收器。
2. **“共同开发约定”文档未提供**：本包按总说明中的技术栈与包边界实现；接口命名以本文件为准，合并时如约定不同，只改适配层，不改规则。
3. **逾期范围**：`scan_overdue()` 标记“借用中”和“待另一方归还确认”且已过有效期限的记录，依据 CP-ST-31“未有效结束”。借用者已交还但物主未确认时仍视为未有效结束，会提醒双方；如团队认为不应限制该情形，需在共同约定中明确后调整。
4. **管理员可见性**：未认领的争议允许任意管理员查看并认领；认领后仅负责管理员和当事双方可查看材料，符合 CP-D-22 的“负责处理的管理员”口径。
5. **管理员关闭争议**：要求双方都已分别确认方案已履行；管理员只解决“结束意见不一致”，不能代替任何一方确认履行。损坏争议关闭后恢复到争议前状态；丢失争议关闭后为“赔偿结清”。
6. **延期**：同一借用同时只允许一条待审批申请；不限制累计次数；待批不改变原期限；批准后不撤销既有逾期标记和限制。
7. **押金退款**：同一借用只发起一次（`deposit_refund_requested_at` 去重）；正常归还在双方确认后请求退款；丢失赔偿结清且争议关闭后请求退款，不要求已归还；损坏争议期间不请求退款。
8. **通知发送**：站内通知在业务动作时同步写入数据库；逾期提醒依赖扫描命令，真实定时调度尚未接入。

## 5. 验证记录

2026-10-29 实际执行：

| 命令 | 结果 |
|---|---|
| `uv run python manage.py check` | 无问题（0 silenced） |
| `uv run python manage.py makemigrations --check --dry-run` | `No changes detected` |
| `uv run python manage.py migrate` | 迁移成功 |
| `uv run python manage.py test` | 43 个测试全部通过（含健康检查） |
| `uv run ruff check apps config tests` | `All checks passed!` |
| `uv run ruff format --check apps config tests` | `30 files already formatted` |
| `uv run python manage.py scan_overdue_loans` | 空库执行，标记 0 笔 |
| 启动开发服务器并请求 | `/health/` 200；`/loans/` 302 到登录；`/static/loans/styles.css` 200；`/admin/login/` 200 |

说明：全仓库 `uv run ruff check .` 仍报告 `docs/` 下历史脚本的 195 个既有问题，本包未改动这些文件。

测试覆盖：

- `test_borrowing.py`：归还时间需双方确认；新时间重置对方确认；过期不能开始；归还双确认；单方确认不结束；非当事人拒绝；重复确认不重复退款；交付前取消。
- `test_extensions.py`：待批不改期限；批准生效并保留历史；到期后申请拒绝；越权审批拒绝；拒绝保留原期限；同时只允许一条待批；跨期批准保留逾期记录和限制；批准时新期限须晚于当前。
- `test_overdue.py`：标记与提醒、限制幂等；通知流转包关闭未选定申请；部分结束不恢复；争议未关闭不恢复；丢失赔偿结清计入有效结束；不影响其他原因限制。
- `test_disputes.py`：争议阻断归还；损坏关闭后恢复并可在归还后退款；丢失结清不写已归还；待归还状态下提交损坏争议；单方同意不关闭；管理员不能代替履行确认；管理员解决意见不一致；认领后材料隔离；重复确认幂等；非当事人拒绝。
- `test_views.py`：登录跳转、列表隔离、详情权限、表单校验、归还流程、GET 拒绝、延期权限、争议材料访问、管理员页面权限、通知私有性与已读状态。

## 6. 未实现或未验证

- 真实第三方支付、退款、结算与到账结果；本包只有退款请求信号。
- 逾期扫描的自动调度（当前为手工命令）。
- 通知的送达渠道与外部推送；只有站内记录。
- 与 A/B 包的实际合并、物品状态联动、未选定申请的实际关闭；需在集成时接入信号接收器。
- 真实管理员裁处流程、赔偿履行的外部证据；系统只记录双方确认，不核验现实履行。
- 借用申请、交付确认、押金支付等 B 包功能；本包只提供接口与前置条件校验。
- 并发与多实例下的限制唯一性：当前未加数据库唯一约束，单实例演示足够；多实例部署前需补约束或事务策略。

## 7. 需求追踪补充

- CP-R-16/17 的“提醒送达”只有站内记录，未验证用户实际看到；`scan_overdue_loans` 未纳入自动调度。
- CP-R-18 的连续多次延期、到期后批准已有服务层测试；旧原型观察不适用。
- CP-R-26/27 的赔偿履行仅为双方确认，不是外部支付或现实履行证明。
- CP-D-21 的实际申请关闭由 B 包接收信号后完成，本包测试只验证信号内容。
