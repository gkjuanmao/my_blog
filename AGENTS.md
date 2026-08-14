# AGENTS.md

- 默认使用中文与用户交流；代码与注释可保留英文。

Django 6 个人博客。UI/admin 文案为中文（`LANGUAGE_CODE='zh-hans'`，`TIME_ZONE='Asia/Shanghai'`）。用 `uv` 管理（Python >= 3.12）。`DESIGN.md` 是设计 SSOT。以下事实均经代码核对。

## 常用命令

- `uv sync` — 安装依赖（runtime + dev 组：ruff/mypy/django-stubs）
- `uv run python manage.py migrate` / `runserver` / `createsuperuser`；局域网访问需用 `runserver 0.0.0.0:8000`（dev 的 `ALLOWED_HOSTS=['*']` 且 `CORS_ALLOW_ALL_ORIGINS=True`）
- docker compose 部署（prod）后仅经 nginx（`:80`）访问：入口 `http://<IP>/`，如 `http://<IP>/api/v1/docs`、`http://<IP>/admin/`；应用 8000 端口不对宿主机暴露
- `uv run ruff check .` — 仅 lint；未配置格式化
- `uv run mypy config articles common users` — 类型检查（django-stubs 插件已在 `pyproject.toml` 配置）
- `uv run pytest` — 运行测试（pytest + pytest-django，`tests/` 独立模块，共 98 个用例）；报告在 `tests/reports/`（`htmlcov/` 已 gitignore）
- pytest 的 `DJANGO_SETTINGS_MODULE` 由 `pyproject.toml` 直接指定为 `config.settings.dev`（绕过 `config/settings/__init__.py` 的 `DJANGO_ENV` 判断），恒走 dev 配置；`testpaths = ["tests"]` 限定只在 `tests/` 收集测试，各 app 内残留的 `tests.py`（如 `articles/tests.py`，为空）不会被运行
- **测试完成后必须清理测试产生的文件**（`media/covers/`、`media/files/`、`media/avatars/` 下的上传文件等），保持工作区干净；`media/` 整体被 gitignore，不应跟踪任何文件（注意：`media/` 下现有文件可能是 DB 中文章真实引用的数据，删除前先核对）

## 配置 / 环境变量

- 环境由 `config/settings/__init__.py` 中的 `DJANGO_ENV` 选择（默认 `dev`）；`DJANGO_SETTINGS_MODULE` 恒为 `config.settings`。
- `dev`：SQLite `db_data/db.sqlite3`（bind mount 持久化，已 gitignore）+ 内存缓存，`DEBUG=True`，硬编码 SECRET_KEY。
- `prod`：`DEBUG=False`，缺 `DJANGO_SECRET_KEY` 会抛 `RuntimeError`。`prod.py` 中的 PostgreSQL/Redis 配置仍是注释 TODO —— prod 目前实际仍用 SQLite。
- `.env` 仅被 docker-compose 的 `env_file` 消费；Django 不会自动加载。本地跑 prod 需手动 export，例如 `DJANGO_ENV=prod DJANGO_SECRET_KEY=x DJANGO_ALLOWED_HOSTS=127.0.0.1 uv run python manage.py runserver`。

## 应用结构

- `users/` — 自定义 `User(AbstractUser + avatar + avatar_name)`；`AUTH_USER_MODEL='users.User'` 在 `base.py` 中设置 —— 不要再加其他用户模型。JWT 基于 `django-ninja-jwt`（读取 `base.py` 中的 `SIMPLE_JWT` 配置）：`users/api.py`（`POST /login/`、`POST /token/refresh/`、`GET /me/`）、`users/authentication.py` 中的 `JWTAuth(HttpBearer)`。
- `articles/` — `Article`/`Category`/`Tag`。公开接口：`GET /categories/`、`GET /tags/`、`GET /articles/`（分页，支持 `category_slug` 过滤）、`GET /articles/search/?keyword=`（返回数组）、`GET /articles/{slug}/`（阅读量 +1）。管理接口（JWT 认证）：`GET /admin/articles/`（含草稿，`is_published`/`keyword`/`category_slug` 过滤+分页）、`POST/PUT/DELETE /admin/articles/...`、`DELETE /admin/articles/slug/{slug}/`（创建/更新为 multipart；封面 JPG/PNG/WebP <=20MB，附件 PDF/Word/HTML <=50MB）、分类/标签完整 CRUD：`POST/GET/PUT/DELETE /admin/categories/...`、`POST/GET/PUT/DELETE /admin/tags/...`（JSON body）。`slug` 创建时可省略：为空由 `title`/`name` 自动生成（`articles/utils.py` `generate_slug` 中文转拼音，依赖 `pypinyin`），冲突由 `unique_slug`（泛化为按 `model` 查询）自动加 `-2` 后缀，手动传入仍优先。
- `common/` — 已实现：`responses.py`（信封 `{code,message,data}`，`code` = HTTP 状态码）、`exceptions.py`（`register_exception_handlers` 覆盖 HttpError/ValidationError/Exception）、`pagination.py`（`CustomPagination`）。`utils.py` 为空。
- 无 `records/`、`comments/`、`blog/` app（已移除）。

## API 路由

- 在 `config/urls.py` 中创建一个 `NinjaAPI` 实例；挂载于 `/api/v1/`，因此真实路径为 `/api/v1/login/`、`/api/v1/me/`、`/api/v1/articles/`、`/api/v1/admin/articles/`、`/api/v1/admin/categories/`、`/api/v1/admin/tags/`。Swagger UI 在 `/api/v1/docs`。
- 响应统一使用 `success_response()` 信封；`HttpError`/`ValidationError`/500 均通过 `common.exceptions.register_exception_handlers(api)` 返回同一信封。
- 分页：`GET /articles/` 在 view 内手动分页（`Query(page, page_size)`，`ge=1`）；输出为信封内 `{items,total,page,page_size}`。

## 易踩坑点

- **默认分类/标签机制**（`articles/defaults.py`）：创建文章时未填分类/标签（含 `0`/空串占位值）自动挂默认分类 `default-category`（名称"默认分类"）与默认标签 `default-tag`（名称"默认标签"）；`AppConfig.ready()` 启动时 `ensure_defaults()` 幂等创建，pytest/mypy 进程内跳过（`sys.modules` 判断）、迁移期捕获 `DatabaseError`。默认分类/标签按 slug 受删除保护（DELETE 返回 400）。
- multipart 下"无分类/标签"的占位值（`''`/`'0'`/`'null'`/非正数）必须归一化为 `None`/`[]`（`articles/schemas.py` `_normalize_category_id`/`_normalize_tag_ids`），否则 `category_id=0` 会触发外键 `IntegrityError`；创建时引用不存在的分类/标签返回 400（"分类不存在"/"标签不存在"）。
- `create_article` 的 `IntegrityError` 不能一律当成 slug 冲突：只有同 slug 记录存在时才报"slug 已存在"（此时会加 `-2` 后缀重试），否则报通用创建失败；插入失败会清理已落盘的 cover/attachment，避免孤儿文件。
- django-ninja 1.6 已移除 `ninja.pagination.Pagination`，且列表接口已改用手动分页（`common/pagination.py` 的 `CustomPagination` 当前未被引用）。
- django-ninja 的 `Schema` 内部有 `model_validator(mode='wrap')`，会把输入包装成只读 `DjangoGetter` —— 在 schema 里写 `mode='before'` 的 `model_validator` 会静默失效（无法修改值），需在 API 层处理（如 slug 自动生成）。
- Django 6 的测试 `Client.put` 默认以 `application/octet-stream` 发送且把 dict `str()` 化 —— PUT 测试须显式传 `content_type='application/x-www-form-urlencoded'` + `urlencode(data)`。
- PUT/PATCH multipart 需要 `ninja.compatibility.files.fix_request_files_middleware`（已在 `base.py` 的 MIDDLEWARE 中）。
- `templates/` 和 `static/` 存在但为空 —— 新增模板/静态文件时创建文件即可。
- `docker-compose.yml` 启动了 postgres+redis 容器，但 `prod.py` 尚未使用它们。
- **Dockerfile 的 `uv sync --frozen` 必须与 `uv.lock` 一起 `COPY`**（`COPY pyproject.toml uv.lock ./`）：只 `COPY pyproject.toml` 会导致容器内缺 lockfile，`uv sync --frozen` 直接退出码 2 构建失败；`.dockerignore` 不应排除 `uv.lock`。
- 宿主机缺 docker compose 插件 / docker.sock 无权限时无法 `docker compose` 或 `docker build` 验证，只能在本机做 YAML 语法校验（`python3 -c "import yaml..."`）。
- **容器数据持久化**：prod 容器中 SQLite 数据库经 bind mount 存宿主机 `db_data/`（容器销毁重建不丢，首次 migrate 前需先 `mkdir -p db_data`）；`media/`、`staticfiles/` 走 named volume（app 与 nginx 共享 media）；`docker compose down` 不删数据，只有 `rm -rf db_data` 才删除数据库。
- `TEST.md` 是面向 AI 的测试用例规范文档（用于生成 pytest 用例），但已落后于实际测试（未覆盖分类/标签/slug 相关用例）——以 `tests/` 实际代码为准。
- Git 仓库已有提交（identity 已配置为 `gkjuanmao`）；提交信息遵循 `DESIGN.md` 9.2 的规范（`feat:`/`fix:`/`docs:`/`refactor:`/`chore:` 前缀）。
