# 需求文档智能审查系统

当前阶段为 S1 教学班与分组。可登录、创建教学班和小组、凭邀请码入班、分组及查看班级总览。上传、版本和审查从下一阶段接入。

| 要查什么 | 入口 |
| --- | --- |
| 首版范围、待确认问题和阶段验收 | [01 启动评审](工程设计/01_启动评审.md) |
| 架构、环境、数据与接口边界 | [02 架构与环境约束讨论稿](工程设计/02_架构与环境约束讨论稿.md) |
| S1 数据约束和验收 | [03 S1 实现与验收](工程设计/03_S1实现与验收.md) |
| 既有需求、模型、状态、验证证据 | [报告材料](docs/README_报告材料.md) · [需求规格说明书](docs/需求规格说明书.md) · [需求追踪矩阵](docs/附件/需求追踪矩阵.md) |
| 现有演示 | [可点击原型](docs/附件/原型/index.html) · [离线报告](docs/附件/实验报告离线阅读.html) |
| 历史资料 | [早期实施方案](历史实施方案.md) · [早期原型与模型原件](历史原件/) |

## 本机启动

进入 `document-review`，使用 Python 3.13 和 uv。

```powershell
uv sync --locked
uv run --locked python manage.py migrate
uv run --locked python manage.py seed_demo
uv run --locked python manage.py runserver 127.0.0.1:8001
```

打开 [本机页面](http://127.0.0.1:8001/)。虚构教师账号为 `demo-teacher-1` 和 `demo-teacher-2`，虚构学生账号为 `demo-student-1` 和 `demo-student-2`，演示密码均为 `Local-review-demo-01`。

先以教师身份建班、创建小组并复制邀请码。切换到学生账号入班，再以教师身份打开班级页面，从学生名单分组。可以用两个浏览器配置文件同时保留教师和学生会话。

```powershell
uv run --locked python manage.py check
uv run --locked python manage.py makemigrations --check --dry-run
uv run --locked python manage.py test
uv run --locked ruff check config classroom manage.py
```

## 历史原型

从本目录运行原型检查（需 Node.js）：

```powershell
Set-Location 'docs/附件/原型'
node check-state.cjs
node check-classroom.cjs
```

原型中仍保留旧联合演示模块以对应历史记录，演示本项目时选择智能审查系统。原型测试只检查预置数据和前端逻辑。工程共用规则见[仓库根目录](../README.md)。
