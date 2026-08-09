# AGENTS.md

- 默认使用中文与用户交流；代码与注释可保留英文。

Django 6 个人博客。UI/admin 文案为中文（`LANGUAGE_CODE='zh-hans'`，`TIME_ZONE='Asia/Shanghai'`）。用 `uv` 管理（Python >= 3.12）。`DESIGN.md` 是设计 SSOT。以下事实均经代码核对。

## 常用命令

- `uv sync` — 安装依赖（runtime + dev 组：ruff/mypy/django-stubs）
- `uv run python manage.py migrate` / `runserver` / `createsuperuser`
- `uv run ruff check .` — 仅 lint；未配置格式化
- `uv run mypy config articles common users` — 类型检查（django-stubs 插件已在 `pyproject.toml` 配置）
- `uv run pytest` — 运行测试（pytest + pytest-django，`tests/` 独立模块，共 62 个用例）；报告在 `tests/reports/`（`htmlcov/` 已 gitignore）
- **测试完成后必须清理测试产生的文件**（`media/covers/`、`media/files/`、`media/avatars/` 下的上传文件等），保持工作区干净；`media/` 整体被 gitignore，不应跟踪任何文件

## 配置 / 环境变量

- 环境由 `config/settings/__init__.py` 中的 `DJANGO_ENV` 选择（默认 `dev`）；`DJANGO_SETTINGS_MODULE` 恒为 `config.settings`。
- `dev`：SQLite `db.sqlite3`（已 gitignore）+ 内存缓存，`DEBUG=True`，硬编码 SECRET_KEY。
- `prod`：`DEBUG=False`，缺 `DJANGO_SECRET_KEY` 会抛 `RuntimeError`。`prod.py` 中的 PostgreSQL/Redis 配置仍是注释 TODO —— prod 目前实际仍用 SQLite。
- `.env` 仅被 docker-compose 的 `env_file` 消费；Django 不会自动加载。本地跑 prod 需手动 export，例如 `DJANGO_ENV=prod DJANGO_SECRET_KEY=x DJANGO_ALLOWED_HOSTS=127.0.0.1 uv run python manage.py runserver`。

## 应用结构

- `users/` — 自定义 `User(AbstractUser + avatar + avatar_name)`；`AUTH_USER_MODEL='users.User'` 在 `base.py` 中设置 —— 不要再加其他用户模型。JWT 基于 `django-ninja-jwt`（读取 `base.py` 中的 `SIMPLE_JWT` 配置）：`users/api.py`（`POST /login/`、`POST /token/refresh/`、`GET /me/`）、`users/authentication.py` 中的 `JWTAuth(HttpBearer)`。
- `articles/` — `Article`/`Category`/`Tag`。公开接口：`GET /categories/`、`GET /tags/`、`GET /articles/`（分页，支持 `category_slug` 过滤）、`GET /articles/search/?keyword=`（返回数组）、`GET /articles/{slug}/`（阅读量 +1）。管理接口（JWT 认证）：`POST/PUT/DELETE /admin/articles/...`（multipart；封面 JPG/PNG/WebP <=5MB，附件 PDF/Word <=20MB）。
- `common/` — 已实现：`responses.py`（信封 `{code,message,data}`，`code` = HTTP 状态码）、`exceptions.py`（`register_exception_handlers` 覆盖 HttpError/ValidationError/Exception）、`pagination.py`（`CustomPagination`）。`utils.py` 为空。
- 无 `records/`、`comments/`、`blog/` app（已移除）。

## API 路由

- 在 `config/urls.py` 中创建一个 `NinjaAPI` 实例；挂载于 `/api/v1/`，因此真实路径为 `/api/v1/login/`、`/api/v1/me/`、`/api/v1/articles/`、`/api/v1/admin/articles/`。Swagger UI 在 `/api/v1/docs`。
- 响应统一使用 `success_response()` 信封；`HttpError`/`ValidationError`/500 均通过 `common.exceptions.register_exception_handlers(api)` 返回同一信封。
- 分页：`GET /articles/` 在 view 内手动分页（`Query(page, page_size)`，`ge=1`）；输出为信封内 `{items,total,page,page_size}`。

## 易踩坑点

- django-ninja 1.6 已移除 `ninja.pagination.Pagination`，且列表接口已改用手动分页（`common/pagination.py` 的 `CustomPagination` 当前未被引用）。
- PUT/PATCH multipart 需要 `ninja.compatibility.files.fix_request_files_middleware`（已在 `base.py` 的 MIDDLEWARE 中）。
- `templates/` 和 `static/` 存在但为空 —— 新增模板/静态文件时创建文件即可。
- `docker-compose.yml` 启动了 postgres+redis 容器，但 `prod.py` 尚未使用它们。
- Git 仓库已初始化但尚无提交（git identity 未配置）。
- `Agent.md` 是过时的代理文档；优先参考本文件。
