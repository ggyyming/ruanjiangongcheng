# A 部分单元测试记录（test_record）

本文件夹用于在软件工程课程交付中**展示 A 部分（账号认证与物品市场：apps/accounts + apps/catalog）测试的案例与结果**。文档只做记录说明，不放测试代码；测试代码位于两个应用的 `tests.py` 与 `tests_views.py`。

## 目录

| 文件 | 内容 |
|---|---|
| `README.md` | 本说明：范围、如何运行、覆盖概览 |
| `单元测试用例表.md` | 全部测试用例（TC-A-01 ~ TC-A-44）：前置条件、输入、预期结果、对应代码 |
| `测试运行记录.md` | 运行环境、执行命令、真实输出、文件覆盖表 |

## 测试的层级与边界

A 部分涉及两个应用，测试分两层，本记录全部纳入：

- **服务层测试**（`apps/accounts/tests.py`、`apps/catalog/tests.py`）：直接调用 `services.py` 中的业务函数，断言返回值、异常类型和数据库状态；一个用例只验证一条业务规则。覆盖 M0 共同接口 `is_verified` / `can_display` / `change_availability`。
- **视图/表单层测试**（`apps/accounts/tests_views.py`、`apps/catalog/tests_views.py`）：经 Django 测试客户端走 HTTP 路由，覆盖注册登录、身份审核闭环、物品发布/审核/公开浏览、越权拒绝、私密字段保护，以及本轮模块 A 的物品图片上传/审核/展示（验收 A1~A5）。

## 如何运行

在 `campus-market/` 目录下执行：

```bash
# 只运行 A 部分账号应用测试（16 个）
uv run python manage.py test apps.accounts

# 只运行 A 部分物品市场测试（28 个）
uv run python manage.py test apps.catalog

# 运行单个用例
uv run python manage.py test apps.catalog.tests.ChangeAvailabilityTest.test_history_not_rewritten
```

## 覆盖概览

A 部分共 **44 个测试**（账号 16 个 + 物品市场 28 个），全部通过（见 `测试运行记录.md`）：

| 测试类 | 覆盖主题 | 用例数 | 主要关联需求 |
|---|---|---|---|
| `IsVerifiedTest` | 校内认证资格判定的各状态与历次申请 | 6 | CP-R-05/06、CP-D-01/02/04 |
| `RegisterLoginTest` | 注册与登录页面 | 2 | CP-R-05 |
| `IdentityFlowTest` | 身份申请/驳回重提/负责管理员认领审核/私密访问 | 6 | CP-R-06/07、CP-D-02/22 |
| `RevokeTest` | 认证撤销：下架公开物品、必填原因 | 2 | CP-D-04 |
| `CanDisplayTest` | 物品公开展示条件（审核状态 + 物主资格） | 5 | CP-R-08、CP-D-03/05 |
| `ChangeAvailabilityTest` | 公开资格变更：校验、留痕、历史不改写 | 6 | M0 共同接口、CP-D-11 |
| `PublishAndReviewTest` | 发布→审核→公开→修改重提→下架/重上架 | 7 | CP-R-08、CP-D-03/05/10/11 |
| `PermissionTest` | 越权拒绝：非物主编辑、非管理员审核、表单校验 | 3 | CP-D-03、AGENTS.md |
| `ItemImageTest` | 物品图片上传/替换/移除/非法拒绝/预留与下架规则 | 7 | 本轮模块 A 验收 A1~A5 |

## 说明

- 与 C 部分记录一样，本文件夹内仅为 `.md` 文档，不含测试代码；`manage.py test` 只收集 `tests*.py` 文件，不受文档目录影响。
- 图片类测试动态生成图片（Pillow 内存生成），不依赖仓库提交的素材文件；使用临时 `MEDIA_ROOT`，不会污染真实上传目录。
