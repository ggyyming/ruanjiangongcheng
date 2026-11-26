# C 部分测试记录（test_record）

本文件夹用于在软件工程课程交付中**展示 C 部分（借用 / 归还 / 延期 / 逾期 / 争议）的测试结果**。

- **测试脚本**统一放在上一级目录 `apps/loans/tests/`（7 个 `.py` 文件，可执行）。
- 本文件夹 `test_record/` 只放**报告**（`.md`），不放测试代码。

## 目录

| 文件 | 内容 |
|---|---|
| `README.md` | 本说明：范围、脚本清单、如何运行 |
| `测试报告.md` | **完整测试报告**：一次列出 C 部分全部 **75 个**用例（测试脚本 / 用例 / 预期结果 / 实际结果），不区分新旧 |

## 测试脚本清单（位于 `apps/loans/tests/`，共 75 例）

| 脚本 | 用例数 | 层级 |
|---|---|---|
| `test_borrowing.py` | 7 | 单元（服务层） |
| `test_disputes.py` | 9 | 单元（服务层） |
| `test_dispute_attachments.py` | 13 | 接口（视图/上传下载） |
| `test_extensions.py` | 9 | 单元（服务层） |
| `test_overdue.py` | 7 | 单元（服务层） |
| `test_views.py` | 12 | 接口（视图） |
| `test_service_rules.py` | 18 | 单元（服务层） |
| **合计** | **75** | — |

## 如何运行

在 `campus-market/` 目录下执行：

```bash
# 运行 C 部分全部测试（75 个），逐条输出
uv run python manage.py test apps.loans -v 2

# 只运行服务层规则补充的单元测试（18 个）
uv run python manage.py test apps.loans.tests.test_service_rules
```

## 说明

- C 部分共 **75 个测试，全部通过**（`Ran 75 tests ... OK`，0 失败 / 0 错误），逐条明细见 `测试报告.md`。
- `apps/loans/tests/_tmp_verify_audit.py` 为仓库原有未跟踪临时脚本（文件名以 `_` 开头，测试发现不会收集），不在 75 个用例内，也未纳入本次交付。
