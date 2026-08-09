# Agent.md

- 默认使用中文与用户交流；代码与注释可保留英文。

Django 6 个人博客（`LANGUAGE_CODE='zh-hans'`，`TIME_ZONE='Asia/Shanghai'`），用 `uv` 管理（Python >= 3.12）。本文档为项目结构说明；`AGENTS.md` 是面向 AI 代理的权威操作文档，`DESIGN.md` 是设计 SSOT。

## 常用命令

- `uv sync` — 安装依赖（runtime + dev 组：ruff/mypy/django-stubs）
- `uv run python manage.py migrate` / `runserver` / `createsuperuser`
- `uv run ruff check .` — 仅 lint（未配置格式化）
- `uv run mypy config articles common users` — 类型检查
- `uv run python manage.py test` — Django 测试框架，非 pytest（暂无测试）

## 配置 / 环境变量

- 环境切换靠 `DJANGO_ENV`（`config/settings/__init__.py`），默认 `dev`；`DJANGO_SETTINGS_MODULE` 恒为 `config.settings`。
- `dev` = SQLite（`db.sqlite3`，已 gitignore）+ 内存缓存，`DEBUG=True`。`prod` = `DEBUG=False`，缺 `DJANGO_SECRET_KEY` 会抛 `RuntimeError`；PostgreSQL/Redis 配置仍是注释 TODO，prod 目前实际仍用 SQLite。
- `.env` 仅被 docker-compose 的 `env_file` 消费；Django 不自动加载。本地跑 prod 需手动 export。

## 应用结构

- `articles/` — 核心业务，已实现 `Article`/`Category`/`Tag` 模型与全部接口（分类/标签/列表/搜索/详情 + 管理 CRUD）
- `users/` — 自定义 `User(AbstractUser + avatar + avatar_name)`；JWT 认证（`django-ninja-jwt`，兼容 `SIMPLE_JWT` 配置）：`POST /login/`、`POST /token/refresh/`、`GET /me/`
- `common/` — `responses.py`（统一信封 `{code,message,data}`，code=HTTP 状态码）、`exceptions.py`（HttpError/ValidationError/Exception 处理器）、`pagination.py`（`CustomPagination`，当前未被引用）；`utils.py` 为空
- 已移除：`records/`、`comments/`、`blog/`（app 由 `blog` 更名为 `articles`）

## 接口

- 前缀 `/api/v1/`：登录 `/api/v1/login/`、文章 `/api/v1/articles/`、管理 `/api/v1/admin/articles/`；Swagger 在 `/api/v1/docs`
- 响应统一为 `{code, message, data}`，成功 code=200（创建 201），失败 code=对应 HTTP 状态码

## 易踩坑点

- `ninja.pagination.Pagination` 在 django-ninja 1.6 已移除，列表接口已改用手动分页（`articles/api.py` 内 `Query(page, page_size)`）
- PUT/PATCH multipart 依赖 `ninja.compatibility.files.fix_request_files_middleware`（已在 base.py）
- `templates/`、`static/` 目录已存在但为空
- 新增模板/admin 代码时沿用中文文案（模型 `verbose_name` 均为中文）
- Git：仓库已 `git init` 但未提交（git identity 未配置）

## 依赖现状

- Django 6.0.7、django-ninja 1.6.2、django-ninja-jwt 5.4.5、django-unfold（Admin 美化）、gunicorn、pillow
- dev 组：ruff、mypy、django-stubs（均已配置）
