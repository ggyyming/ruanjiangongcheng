# A 包开发记录（CAMPUS-A）

- 任务：CAMPUS-A（账号认证与物品市场）
- 负责人：熊超凡（GitHub：uheuhfue）
- 分支：`codex/a-uheuhfue`；基于 main：`4b2b135`
- 日期：2026-10-29

## 1. 已完成（A0 + A1）

| 里程碑 | 内容 | 状态 |
|---|---|---|
| A0 | IdentityApplication / Item / ItemAvailabilityChange 模型与初始迁移 | 已提交（751407b） |
| A0 | M0 接口：`accounts.services.is_verified`、`catalog.services.can_display`、`catalog.services.change_availability` | 已提交 |
| A0 | templates/base.html 公共模板 | 已提交 |
| A1 | 注册/登录/退出、个人主页、身份申请与管理员审核（驳回重提、历次保留） | 已完成，待提交 |
| A1 | 物品发布/修改重提/内容审核/公开列表与详情/下架与重新上架 | 已完成，待提交 |
| A1 | 认证撤销（下架未预留公开物品）与私密字段访问控制 | 已完成，待提交 |
| 验证 | `manage.py test apps.accounts apps.catalog` 共 36 项通过；`ruff check apps` 通过 | 2026-10-29 实测 |

## 2. 预存 lint 问题记录（不在 A 包范围内，未修改原文件）

`ruff check .` 全仓库共 195 个错误，经核对**全部位于工程底座原有文件**（`config/`、`manage.py` 等，由 django-admin 生成），不属于 A 包：

- 位置：`config/settings.py`、`config/urls.py`、`config/views.py`、`config/asgi.py`、`config/wsgi.py`、`manage.py`
- 类型：以 E501（行过长）为主，另有 import 排序（I001）等
- 处理建议：属集成者"公共接线"范围，由集成 PR 统一修复并锁版本；A 包不越界修改。
- 附注：A 包已通过 `pyproject.toml` 增加 `per-file-ignores`（迁移文件忽略 E501），该公共配置改动在 PR 中单列。

## 3. ponytail 待接入项（依赖 B/C，已留注释）

| 项 | 依赖 | 位置 |
|---|---|---|
| 联系方式和具体地点"预留后向双方显示" | B 提供预留当事人查询 | `apps/catalog/views.py` item_detail |
| 有进行中流转时禁止修改物品 | B 提供进行中流转事实接口 | `apps/catalog/services.py` edit_item |
| 认证撤销时通知双方 | C 的通知服务 | `apps/accounts/services.py` revoke_identity |
| 物品图片上传（类型/大小限制） | 集成者协调 Pillow 依赖 | `apps/catalog/models.py`（A2 实现） |
| "负责管理员"对象级授权（当前以 is_staff 简化） | 管理员体系明确 | `apps/accounts/views.py`、`apps/catalog/views.py` |

## 4. 交接格式（PR 正文用）

```text
任务：CAMPUS-A；负责人：熊超凡 / @uheuhfue
分支与 PR：codex/a-uheuhfue → main；基于 main：4b2b135；交付提交：【待填写】
已完成：A0 模型与 M0 接口、A1 认证与物品审核闭环（CP-R-05/06/07/08、CP-D-01/02/03/04/05/10/11/22 相关部分）
文件与迁移：apps/accounts、apps/catalog 及各自 migrations/0001_initial.py；templates/base.html；config 接线（INSTALLED_APPS、TEMPLATES DIRS、根路由与 items 路由、pyproject per-file-ignores）
接口：is_verified / can_display / change_availability（签名见共同开发约定 M0）
验证：uv run python manage.py test apps.accounts apps.catalog → 36 项通过；ruff check apps 通过
遗留或阻塞：见本文第 2、3 节（预存 lint 问题、B/C 依赖项、图片上传）
```
