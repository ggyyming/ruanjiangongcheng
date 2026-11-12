# 共用上传配置修改报告

**收件人**　A 组物品图片负责人、C 组借用争议附件负责人。

共用上传配置位于 `campus-market/` 工程。请从集成方公布的、已包含这份报告的基线更新各自的功能分支，然后使用下面的依赖和目录。具体权限与业务验收用例见[三模块开发与分支交接说明](下一轮三模块开发与分支交接说明.md)。

| 文件 | 统一配置 |
| --- | --- |
| [pyproject.toml](../../../pyproject.toml)、[uv.lock](../../../uv.lock) | Pillow 由项目统一管理，当前锁定 `13.0.0`。运行 `uv sync --frozen` 安装锁定版本。 |
| [config/settings.py](../../../config/settings.py) | `MEDIA_ROOT = BASE_DIR / "var" / "uploads"`，使用 Django 默认的本地文件存储。首次保存时由存储后端创建所需子目录。 |
| [仓库根 .gitignore](../../../../.gitignore) | 忽略 `campus-market/var/uploads/`，避免把本地上传文件带入 PR。 |

上传目录只用于存储。图片或附件通过所属应用的命名路由提供，由视图在每次请求时检查可见性。模板使用 `{% url ... %}` 生成地址，文件视图从 Django 存储打开文件。存储路径和访问 URL 分开处理。

首轮文件格式统一为 JPEG、PNG，单份上限 5 MiB，宽高各不超过 4096 像素。各应用在自己的表单或服务里落实校验。A 每件物品一张图，C 每笔争议最多五份附件。

## A 组 物品图片

- 在 `apps/catalog/` 把可选图片接入 `Item`、`ItemForm` 和发布、编辑、审核页面。表单使用 `multipart/form-data`，视图绑定 `request.FILES`，文件按 `items/` 前缀存入共用目录。
- 用 Pillow 验证 JPEG、PNG 的真实格式、可解码性、大小和尺寸，按分工说明重新编码并清除原图元数据。保留原图、替换和主动移除要有明确的表单行为。
- 图片路由复用现有物品公开和详情访问规则。审核员和物主可预览待审图。对访客检查 `can_display`，并验证替换、重新送审、下架后旧地址失效。
- 提交 `catalog` 的增量迁移和本模块测试。重点验证待审图片权限、换图后重审和非法文件被拒绝。

## C 组 借用争议附件

- 在 `apps/loans/` 接入附件模型、争议详情上传表单和受控下载路由。文件按 `disputes/` 前缀存入共用目录，存储键由服务端生成，原文件名用于显示。
- 用 Pillow 验证 JPEG、PNG 的真实格式、可解码性、大小和尺寸。已通过校验的原始内容作为证据保留。上传仅允许处理中争议的双方，关闭后历史附件仍可由授权角色下载。
- 下载视图复用 `Dispute.can_view` 并校验附件和争议的对应关系。当事双方与负责管理员可下载。未认领管理员、无关账号和无分配关系的超级管理员均无下载权限。用附件响应下载，避免直接暴露存储路径。
- 提交 `loans` 的增量迁移和本模块测试。重点验证对象越权、关闭后拒绝新上传、已授权历史下载及附件上限。

## 开工和交接

切到各自从统一基线创建的分支。已有功能分支的成员先合入集成方公布的提交，再进入 `campus-market/` 运行以下命令。

```powershell
uv sync --frozen
uv run python manage.py migrate
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
```

A 组运行 `uv run python manage.py test apps.catalog`，C 组运行 `uv run python manage.py test apps.loans`。上传测试使用临时存储目录和虚构图片。PR 列出应用路由、迁移文件、角色权限和实际测试结果。依赖锁和全局存储沿用共用基线，确需调整时在 PR 中列出理由及影响。

## 本次验证

在 Windows 和 Python 3.13.15 的临时环境中，`uv sync --frozen` 成功安装 Pillow 13.0.0。使用 Django 默认存储在两个子目录写入并读回测试图片，确认直接请求上传文件路径在 `DEBUG` 开启和关闭时都返回 404。项目现有 134 项测试全部通过，Django 系统检查、迁移一致性检查和 Ruff 也通过。
