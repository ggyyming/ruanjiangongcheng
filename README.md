# 软件工程课程项目

这是一个面向课程设计的 Django 工程底座。当前只包含通用开发环境和项目结构，业务选题确定后再添加业务模块。

## 环境要求

- Python 3.13
- uv
- Git

## 首次启动

```powershell
uv sync
uv run python manage.py migrate
uv run python manage.py runserver
```

浏览器访问 `http://127.0.0.1:8000/health/`，应看到 `{ "status": "ok" }`。

## 常用检查

```powershell
uv run python manage.py check
uv run python manage.py test
uv run ruff check .
uv run ruff format --check .
```

## 目录约定

- `config/`：Django 全局配置、路由和服务入口。
- `apps/`：后续按业务领域添加 Django 应用。
- `docs/`：需求、架构和设计文档。
- `.venv/`：本项目专用虚拟环境，不提交到 Git。

架构原则参见 [docs/architecture.md](docs/architecture.md)。
