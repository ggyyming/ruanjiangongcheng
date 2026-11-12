# 软件工程课程项目

这是校园物品流转平台的 Django 项目。用户可以浏览经审核的物品，通过校内身份审核后可发布或申请买卖、赠送和借用。付款、结算和退款均为模拟。

## 环境要求

- Python 3.13
- uv
- Git

## 首次启动

```powershell
uv sync --frozen
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

浏览器打开 [物品市场](http://127.0.0.1:8000/)。已有管理员账号时可以跳过创建步骤。健康检查地址为 `/health/`。

## 演示流程

1. 注册两个演示用户，分别提交虚构校内身份资料。用管理员账号登录，在「我的账户 → 身份审核」认领并审核。
2. 一个用户发布物品，管理员在「物品审核」通过后，另一个用户从物品详情提交流转申请。物主从「查看物品申请」选择接收方，双方从「我的流转」进入详情。
3. 赠送由双方确认交付。买卖由接收方发起模拟付款，收到成功回执后双方确认交付，再单独处理结算。借用先由双方确认归还时间和押金，再模拟付款及确认借出。借用人确认交还、物主确认收回后，系统发起押金退款。

买家或借用人在「流转详情 → 交付进度」点击「模拟支付货款」或「模拟支付押金」，即可完成模拟付款。借用须先确认归还时间和押金。付款完成后仍需双方分别确认交付。

超级管理员可打开 [数据控制台](http://127.0.0.1:8000/data/)，新增、编辑或删除普通账号及交付与流转操作记录。删除使用后台确认页，账号存在关联数据时会显示删除影响或数据库保护限制。操作记录是流转日志，交付状态通过业务流程推进。「模拟资金流水」仍提供付款、结算和退款的模拟回执，支持成功、失败或未知。

终端也可以提交回执。运行以下命令时将 `123` 替换成资金明细里显示的实际操作编号：

```powershell
uv run python manage.py simulate_receipt --operation-id 123 --result success
```

回执结果也可以用 `failure` 或 `unknown`。用以下命令扫描付款超时、迟到入账、退款与结算重试以及借用逾期：

```powershell
uv run python manage.py process_market_jobs
```

演示可手动执行扫描。需要定时运行时，可由 Windows 任务计划程序在项目目录每分钟调用一次该命令。

## 常用检查

```powershell
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py test
uv run ruff check apps config tests manage.py
```

## 工程导航

从 [工程索引](PROJECT_INDEX.md) 查找正式运行代码、课程材料、历史交接和提交成品。各版本和历史材料见 [记录](记录/README.md)。按具体文件查找时打开 [逐文件清单](docs/FILE_INDEX.md)。架构与技术选型见 [工程架构](docs/architecture.md)。
