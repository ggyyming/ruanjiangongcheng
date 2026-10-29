# 任务C：借用争议与通知（独立交付包）

版本：1.0；日期：2026-10-29；适用主题：校园物品流转平台，业务包 C。

本目录是任务 C 的完整独立交付物。当前仓库底座**没有安装**本包（`apps/` 下无业务应用，`config/` 未修改）；整合时按第 2 节复制应用并应用配置补丁即可，不影响其他成员的包。

## 1. 目录结构

```text
任务C/
├─ README.md                         本文件：整合步骤与接口
├─ 验证记录.md                       实际执行的命令、结果与限制
├─ apps/
│  └─ loans/                         完整 Django 应用
│     ├─ models.py                   借用约定、延期、争议、逾期限制、通知、争议留痕
│     ├─ services.py                 业务规则与状态转换
│     ├─ signals.py                  与 A/B 包的跨包信号
│     ├─ forms.py / views.py / urls.py
│     ├─ templates/loans/            借用、争议、通知、管理员页面
│     ├─ static/loans/styles.css
│     ├─ management/commands/scan_overdue_loans.py
│     ├─ migrations/0001_initial.py
│     ├─ admin.py
│     └─ tests/                      44 个规则、权限与页面测试
├─ config/
│  ├─ 任务C配置.patch                对 settings.py、urls.py 的 unified diff
│  └─ 配置修改说明.md                补丁冲突时的手改说明
└─ 文档/
   └─ 任务C_借用争议与通知.md         范围、规则映射、决策、未验证项
```

## 2. 整合步骤

在目标仓库根目录执行：

```bash
# 1. 复制应用
cp -r 任务C/apps/loans apps/

# 2. 应用配置补丁（基于 main 提交 4b2b135）
git apply --check 任务C/config/任务C配置.patch
git apply 任务C/config/任务C配置.patch

# 3. 安装与验证
uv sync
uv run python manage.py migrate
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py test
```

补丁只做三件事：`INSTALLED_APPS` 增加 `apps.loans`；增加临时 `LOGIN_URL = "admin:login"`；在 `config/urls.py` 挂载 `path("loans/", include("apps.loans.urls"))`。若 A/B 包已改过这两个文件，只合并这三处，冲突处理见 `config/配置修改说明.md`。

整合后还需要：

1. 把 `BorrowAgreement.item_ref`、`application_ref` 两个字符串字段替换为 A/B 包的外键（数据字典中的物品、流转申请），保持字段含义不变。
2. 由 A 包接入自有登录页后，把 `LOGIN_URL` 改为 A 的登录路由；本包页面使用 `@login_required`，会自动跟随。
3. 由 B 包实现第 3.2 节的三个信号接收器；否则退款、物品下架、未选定申请关闭只有记录，不会产生实际业务效果。
4. 若团队统一了 URL 前缀，只改 `include()` 的挂载路径，模板均使用 `{% url 'loans:...' %}`。

## 3. 跨包接口

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

# 交付双确认且押金支付成功后；本包不校验资金记录
services.start_borrow(agreement)

# 交付前取消
services.cancel_unstarted_agreement(agreement, reason)

# 创建借用申请前检查资格（CP-R-09）
services.is_borrow_restricted(user)

# 判断交付、退款、撤销条件
agreement.has_open_dispute()
```

### 3.2 本包发出的信号（`apps/loans/signals.py`）

| 信号 | 参数 | 处理方 | 用途 |
|---|---|---|---|
| `deposit_refund_requested` | `agreement`、`reason` | B（资金） | 创建全额原路退款记录并回写结果；同一借用只发一次 |
| `borrow_ended` | `agreement`、`outcome`（`returned`/`compensated`/`cancelled`） | A/B（物品、流转） | 物品保持下架；归还或赔偿结清后不自动重新开放（CP-D-11） |
| `borrow_applications_should_close` | `user`、`reason` | B（申请） | 关闭逾期用户尚未被选定的借用申请（CP-D-21） |

### 3.3 站内通知

A/B 需要发送身份审核、付款、交付等通知时调用：

```python
from apps.loans.services import notify
from apps.loans.models import Notification

notify(
    user,
    business_kind=Notification.Business.FUNDS,
    business_ref=payment.pk,
    event="funds.payment_succeeded",
    title="货款支付成功",
    body="支付结果以第三方回执为准。",
)
```

通知只记录发送与已读时间，不改变业务状态（CP-D-20）。

## 4. 覆盖范围

- 需求：CP-R-03、04、14、15、16、17、18、26、27；CP-R-21 中“记录双方押金金额”的部分，收付由 B 负责。
- 细则：CP-D-06、07、11、12、14、15、16、19、20、21、22。
- 转换：CP-ST-09 至 12、19、25 至 29、31、35、36。
- 未覆盖：借用申请与交付确认、押金收付、物品状态、校内身份审核（均属 A/B 包）。

详细映射见 `文档/任务C_借用争议与通知.md`。

## 5. 验证状态

在 `git worktree` 干净检出提交 `4b2b135` 上，按第 2 节复制应用并打补丁后重新执行：`check`、`makemigrations --check`、`migrate`、`test`（44 个通过）、`ruff check apps config tests`、`ruff format --check apps config tests` 全部通过。

整合前的完整运行还验证了 `/health/` 200、`/loans/` 302 到登录页、静态样式 200、`/admin/login/` 200，以及 `scan_overdue_loans` 命令执行。命令与结果见 `验证记录.md`。

## 6. 假设与限制

1. **跨包依赖**：仓库没有 A/B 代码，本包只依赖 `settings.AUTH_USER_MODEL`，物品与申请用标识加名称快照保存；合并时替换为外键。
2. **缺少共同开发约定**：本包按总体说明的技术栈与业务边界实现；接口命名以第 3 节为准，如团队约定不同，只改适配层，不改规则。
3. **逾期范围**：“借用中”和“待另一方归还确认”超期都会标记逾期（CP-ST-31“未有效结束”）。若团队认为已交还但物主未确认时不应限制借用者，需统一约定后调整。
4. **管理员可见性**：未认领的争议允许任意管理员查看并认领；认领后仅负责管理员和当事双方可看材料。
5. **管理员关闭**：要求双方都确认方案已履行，管理员只解决“结束意见不一致”，不能代替任何一方确认履行。
6. **押金退款**：同一借用只请求一次；退款是否成功、何时到账由资金包记录，本包不宣称到账。
7. **逾期扫描**：未引入 Celery/Redis，需要计划任务定期执行 `uv run python manage.py scan_overdue_loans`。
8. **并发**：新增借用限制未加数据库唯一约束，单实例演示足够；多实例部署前需补约束或事务策略。
9. **未验证**：真实支付/退款、外部通知送达、与 A/B 的实际合并、现实赔偿履行证明。
