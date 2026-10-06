# AGENTS.md

- 默认使用中文与用户交流；代码与注释可保留英文。

Django 6 个人博客。UI/admin 文案为中文（`LANGUAGE_CODE='zh-hans'`，`TIME_ZONE='Asia/Shanghai'`）。用 `uv` 管理（Python >= 3.12）。`DESIGN.md` 是设计 SSOT。以下事实均经代码核对。

## 常用命令

- **部署运维统一入口：`scripts/blog.sh <子命令>`**（预检/启动/停止/状态/日志/质量门禁/导出/导入/演示数据/清理，见 `scripts/blog.sh help`）—— 它把“podman-compose 不会因镜像变更重建容器”、“SELinux 需 `:z`”、“`.env` 必填校验”、“轮询等就绪”等实测坑点固化成了代码，优先用它而不是手敲步骤。
- **脚本自动识别容器工具链**：按 `docker compose(v2)` → `docker-compose(v1)` → `podman-compose` → `podman compose` 的顺序探测（docker 要求 daemon 可达，避免只装了 CLI 就误判），也可用 `BLOG_ENGINE=docker|podman` 强制指定。差异已内部抹平：容器名（podman `_1` / docker `-1`）按 compose 标签解析、`docker save` 不带 `-m`、镜像名 `localhost/` 前缀差异会自动补标签。
- `uv sync` — 安装依赖（runtime + dev 组：ruff/mypy/django-stubs）
- `uv run python manage.py migrate` / `runserver` / `createsuperuser`；局域网访问需用 `runserver 0.0.0.0:8000`（dev 的 `ALLOWED_HOSTS=['*']` 且 `CORS_ALLOW_ALL_ORIGINS=True`）
- docker compose 部署（prod）后仅经 nginx（`:18888`）访问：入口 `http://<IP>:18888/`、`http://<IP>:18888/admin/`；应用 8000 端口不对宿主机暴露。Swagger UI（`/api/v1/docs`）生产默认关闭（仅 `DEBUG` 或 `ENABLE_API_DOCS=true` 才开放）
- `uv run ruff check .` — 仅 lint；未配置格式化
- `uv run mypy config articles common users` — 类型检查（django-stubs 插件已在 `pyproject.toml` 配置）
- `uv run pytest` — 运行测试（pytest + pytest-django，`tests/` 独立模块）；**用例数随迭代变化，以 `uv run pytest --collect-only -q | tail -1` 为准（当前 336 个）**；`tests/reports/` 是本地报告产物（junit/覆盖率），已 gitignore、不入库
- pytest 的 `DJANGO_SETTINGS_MODULE` 由 `pyproject.toml` 直接指定为 `config.settings.dev`（绕过 `config/settings/__init__.py` 的 `DJANGO_ENV` 判断），恒走 dev 配置；`testpaths = ["tests"]` 限定只在 `tests/` 收集测试，各 app 内残留的 `tests.py`（如 `articles/tests.py`，为空）不会被运行
- `tests/conftest.py` 有 autouse 的 `media_root` fixture，把 `MEDIA_ROOT` 隔离到 `tmp_path`，所以 pytest 上传的文件不会落进真实 `media/`（早期版本会污染）；仍需清理的是手工/接口联调产生的文件
- **手工测试后必须清理上传产生的文件**（`media/covers/`、`media/files/`、`media/avatars/` 下的上传文件等），保持工作区干净；`media/` 整体被 gitignore，不应跟踪任何文件（注意：`media/` 下现有文件可能是 DB 中文章真实引用的数据，删除前先核对）
- 测试 PUT multipart 时不能用 `api_client.put(url, dict, ...)`：Django 6 测试客户端的 `put()`/`patch()` 只做 `_encode_json`，不做 multipart 编码，dict 会被 `str()` 化成非法 body（表现为 200 但字段全未更新）。须手工 `encode_multipart(BOUNDARY, data)` 并传 `MULTIPART_CONTENT`（见 `tests/test_update_article.py`）
- **git 提交约定**：用户说"提交代码/提交"时，默认在本地按提交规范（DESIGN.md 9.2：`feat:`/`fix:`/`docs:`/`refactor:`/`chore:` 前缀 + 中文描述）提交后**直接推送到远端**（`git push`），无需再询问。
  - 远端走 SSH：`origin` = `ssh://git@192.168.31.96:222/gkjuanmao/my_blog.git`（Gitea 的 SSH 端口是 **222**，不是 22；scp 风格地址 `git@192.168.31.96:gkjuanmao/my_blog.git` 也能用，靠 `~/.ssh/config` 的 Host 块补端口）。
  - 认证用公钥：`~/.ssh/id_ed25519`，公钥已在 Gitea 注册为 `zcode@PC-GKjuanmao`。Gitea 的 SSH **只开 publickey**，账号密码对 SSH 无效（密码仅用于 Gitea Web/API）。
  - 本仓库已配置仓库级提交身份（`user.name=gkjuanmao`、`user.email=gkjuanmao@example.com`），`git commit` 直接提交即可，无需再带 `-c user.name=... -c user.email=...`。

## 配置 / 环境变量

- 环境由 `config/settings/__init__.py` 中的 `DJANGO_ENV` 选择（默认 `dev`）；`DJANGO_SETTINGS_MODULE` 恒为 `config.settings`。
- `dev`：SQLite `db_data/db.sqlite3`（bind mount 持久化，已 gitignore）+ 内存缓存，`DEBUG=True`，硬编码 SECRET_KEY。
- `prod`：`DEBUG=False`，缺 `DJANGO_SECRET_KEY` 会抛 `RuntimeError`。TLS/CSRF/缓存均已环境化：`DJANGO_USE_TLS=true` 才开启 `SECURE_SSL_REDIRECT`/安全 Cookie/`SECURE_PROXY_SSL_HEADER`，`DJANGO_SECURE_HSTS_SECONDS`（默认 0）控制 HSTS，`DJANGO_CSRF_TRUSTED_ORIGINS` 配置信任来源，设置 `REDIS_URL` 则用 Redis 缓存（否则回落 LocMemCache）；`ALLOWED_HOSTS` 空值回落 `localhost,127.0.0.1`。`prod.py` 中的 PostgreSQL 配置仍是注释 TODO —— prod 目前实际仍用 SQLite（docker-compose 已不含 db 服务，但保留 redis 服务）。
- `.env` 仅被 docker-compose 的 `env_file` 消费；Django 不会自动加载。本地跑 prod 需手动 export，例如 `DJANGO_ENV=prod DJANGO_SECRET_KEY=x DJANGO_ALLOWED_HOSTS=127.0.0.1 uv run python manage.py runserver`。

## 应用结构

- `users/` — 自定义 `User(AbstractUser + avatar + avatar_name)`；头像落盘路径 `avatars/%Y/%m/UUID.ext`，`users/models.py` 的 `validate_avatar` 限制 JPG/PNG 且 ≤2MB（对齐 DESIGN 4.1/7.2）。`AUTH_USER_MODEL='users.User'` 在 `base.py` 中设置 —— 不要再加其他用户模型。JWT 基于 `django-ninja-jwt`（读取 `base.py` 中的 `SIMPLE_JWT` 配置）：`users/api.py`（`POST /login/`、`POST /token/refresh/`、`GET /me/`）、`users/authentication.py` 中的 `JWTAuth(HttpBearer)`。
  - `POST /login/` 有失败限流：同一「客户端 IP（取 `X-Forwarded-For` 最后一段）+ 用户名」连续失败 5 次锁定 5 分钟（缓存实现，`LOGIN_MAX_ATTEMPTS`/`LOGIN_LOCKOUT_SECONDS`），命中返回 429。
  - `POST /token/refresh/` 会轮换 refresh：返回新的 `access` **与新的 `refresh`**，旧 refresh 进黑名单（`ROTATE_REFRESH_TOKENS` + `BLACKLIST_AFTER_ROTATION=True`，依赖 `ninja_jwt.token_blacklist` app，已含迁移）。
- `articles/` — `Article`/`Category`/`Tag`。公开接口：`GET /categories/`、`GET /tags/`、`GET /articles/`（分页，支持 `category_slug` 过滤）、`GET /articles/search/?keyword=`（**分页信封** `{items,total,page,page_size}`，参数含 `page`/`page_size`）、`GET /articles/{slug}/`（阅读量 +1；返回**服务端渲染并消毒**的 `content_html`）。管理接口（JWT 认证）：`GET /admin/articles/`（含草稿，`is_published`/`keyword`/`category_slug` 过滤 + 分页 + `ordering` 排序，白名单：`publish_time`/`created_at`/`updated_at`/`views`/`title`，非法值返回 400）、`POST/PUT/DELETE /admin/articles/...`、`DELETE /admin/articles/slug/{slug}/`（创建/更新为 multipart；封面 JPG/PNG/WebP 上传 ≤20MB、**必填**（服务端统一压成 WebP，见下），附件 PDF/Word <=50MB、**可缺省**；**删除文章会经 `articles/signals.py` 的 `post_delete` 同步清理封面/附件文件**）、分类/标签完整 CRUD：`POST/GET/PUT/DELETE /admin/categories/...`、`POST/GET/PUT/DELETE /admin/tags/...`（JSON body）。
  - **Markdown 正文与内联图**（2026-10 新增，方案见 `docs/ARTICLE_MARKDOWN_PLAN.md`）：`Article.content` 存 Markdown 原文；`articles/rendering.py` 负责**服务端渲染 + 消毒**（Python-Markdown → nh3 白名单 → `html.parser` 回填 `loading/decoding/target/rel`）。公开详情返回 `content_html`，管理详情（`AdminArticleDetailOut`）额外返回 `content` 原文供编辑回填。
  - `POST /admin/articles/preview/`（渲染预览，不落库）、`POST /admin/articles/images/`（staff；上传题图 → 压成 WebP → **内容寻址**落盘 `media/inline/<sha256[:32]>.webp` → 返回 URL）。两条路由都是 `articles` 后**单段**路径，必须注册在 `/admin/articles/{article_id}/` **之前**。
  - 内联图生命周期由 `manage.py purge_inline_images`（默认 dry-run，`--delete` 生效）唯一负责：回收站 + 两遍扫描 + fail-closed 守卫。
  - **HTML 导入**（2026-10 新增）：`POST /admin/articles/convert-html/`（staff；同为 `articles` 后单段路径，须早于详情路由）把手机/第三方导出的 HTML 转成 Markdown，实现在 `articles/convert.py`：bs4 先处理内联图 → nh3 预清洗 → markdownify → 空白规范化。**内联图必须在 nh3 之前处理**（nh3 按 `url_schemes` 会剥掉 `data:` 的 src，base64 图会在转换前就丢）；base64 图走 `process_inline_image`/`store_inline_image` 压成 WebP 内容寻址落盘（同图自动去重），外链图保留原样，`file://` 等不可读来源移除并告警。输入走 multipart **文件**通道（`HTML_IMPORT_MAX_BYTES=100MiB`，对应 nginx 上该路由**独立 location** 的 `client_max_body_size 110m` —— 不能只调大全局 `/api/` 的 60m，否则连带放宽封面/附件等所有普通接口）：`DATA_UPLOAD_MAX_MEMORY_SIZE`（默认 2.5MB）只约束 `request.body`/表单字段、**不含文件数据**，而手机导出的 HTML 常因内嵌图远超它（`tests/test_convert_html.py::test_large_html_goes_through_file_channel` 用 3MB 用例钉住）。上传文件时额外返回 `suggested_title`（`articles/utils.py` `suggest_title_from_filename`：去掉扩展名与尾部时间戳/序号，如 `44 上海-罗马_202610030035_06899.html` → `44 上海-罗马`），前端**仅在标题为空时**回填。
  - 封面压缩由 `articles/covers.py` 唯一负责（上传端点与归档导入共用），存量回收用 `manage.py recompress_covers`。
  - `slug` 创建时可省略：为空由 `title`/`name` 自动生成（`articles/utils.py` `generate_slug` 中文转拼音，依赖 `pypinyin`），冲突由 `unique_slug`（泛化为按 `model` 查询）自动加 `-2` 后缀，手动传入仍优先。
- `common/` — 已实现：`responses.py`（信封 `{code,message,data}`，`code` = HTTP 状态码）、`exceptions.py`（`register_exception_handlers` 覆盖 HttpError/ValidationError/Exception）。列表接口均为手动分页，故原 `pagination.py`（`CustomPagination` 自 django-ninja 1.6 起已不可用）与空文件 `utils.py` 已删除。
- 无 `records/`、`comments/`、`blog/` app（已移除）。

## API 路由

- 在 `config/urls.py` 中创建一个 `NinjaAPI` 实例；挂载于 `/api/v1/`，因此真实路径为 `/api/v1/login/`、`/api/v1/me/`、`/api/v1/articles/`、`/api/v1/admin/articles/`、`/api/v1/admin/categories/`、`/api/v1/admin/tags/`。Swagger UI 在 `/api/v1/docs`（仅 `DEBUG=True` 或 `ENABLE_API_DOCS=true` 时注册，生产默认 404）。
- 响应统一使用 `success_response()` 信封；`HttpError`/`ValidationError`/500 均通过 `common.exceptions.register_exception_handlers(api)` 返回同一信封。
- 分页：`GET /articles/` 在 view 内手动分页（`Query(page, page_size)`，`ge=1`）；输出为信封内 `{items,total,page,page_size}`。
- **文章归档（导入/导出，仅 staff）**：`GET /admin/articles/export/` 与 `/export/estimate/`（**必须早于详情路由**，见下）、`GET /admin/archives/{ticket}/`（能力 URL、`auth=None`、单次使用、重复访问 410、可 `POST .../reissue/` 重签）、两阶段导入 `POST /admin/articles/import/stage/`（上传+校验，返回 `staged_id` 与预检报告）与 `POST /admin/articles/import/commit/`（JSON 传 `staged_id`，不重传文件）、`DELETE /admin/articles/import/stage/{id}/`、`GET /admin/articles/import/limits/`。实现见 `articles/archive/`（`export`/`validate`/`planner`/`importer`/`locks`/`staging`/`limits`/`format`/`errors`），方案与 D1–D24 决策见 `docs/ARTICLE_IMPORT_EXPORT.md`，产物清扫用 `manage.py purge_archives`。
  - **格式已是 v2**（2026-10）：`article.json` 增加 `content`（Markdown 原文）与 `images`（正文插图，包内 `images/<内容寻址名>.webp`），`attachment` 可为 `null`。导入**同时接受 v1/v2**：v1 能导入但不含正文与插图，会显式告警（`LEGACY_ARTICLE_SCHEMAS`）。`SCHEMA_ARTICLE`/`SCHEMA_ARCHIVE` 是**我们写出的版本**，`ACCEPTED_*` 是接受集，`REPORT_SCHEMA` 是报告输出（三者不可混用）。
  - 容量按**实际条目**配平（不再用"篇数×3"）：`ARCHIVE_MAX_ENTRIES=2000`、`TOTAL_UNCOMPRESSED=1GiB`、`JSON_BYTES=2MiB`；导出与导入用**同一实际总数**（含固定成员 manifest/README 与每张图），否则会产出自己导不回的包。
  - `validate_package` **不驻留媒体字节**（只留 `stored_sha256`），importer 按需重开暂存 zip 并**重跑** `process_cover`/`process_inline_image` 后用**产物**哈希比对——直接拿原始字节比对会让所有需重编码的文件误判失败。

## 易踩坑点

- **文章归档（导入/导出）路由顺序敏感**：`GET /admin/articles/export/` 必须注册在 `GET /admin/articles/{article_id}/` **之前**——详情路由没有 int 转换器，`resolve()` 会把 `export` 解析成 `article_id`（实测）。`tests/test_archive_export.py::TestArchiveRouting` 钉住了这一点。
- 归档产物（导出包/回滚包/导入暂存）落在 `ARCHIVE_ROOT`（默认 `private_archives/`，已 gitignore），**绝不能在 `MEDIA_ROOT` 下**：nginx 对 `/media/` 无鉴权且 `expires 7d`。
- 媒体幂等靠 `Article.cover_image_sha256` / `file_sha256`，语义是**当前落盘文件的字节哈希**：**绝不**用「源字节哈希」比对，否则任何需重编码的文件每轮都会因哈希不等被重写（实测教训）。
- **封面统一压成 WebP（2026-10 新增）**：实现在 `articles/covers.py`，上传端点与归档导入**共用同一条管线**（`process_cover` → 最长边 ≤ `COVER_MAX_LONG_EDGE`(1600)、质量 `COVER_WEBP_QUALITY`(82)、剥 EXIF/ICC）。因此**落盘扩展名恒为 `.webp`**，调用方不能用原始文件名后缀拼路径（否则「.jpg 里装 WebP 字节」，nginx 按扩展名发错 Content-Type）；`cover_image_name` 仍是原始文件名（展示用）。两条硬规则：① **已达标就原样返回**（WebP + 尺寸达标 + 无元数据 + 尾部无附加数据），这是导出→导入幂等的前提；② **MPO 必须当 JPEG 收**——手机（尤其 iPhone）人像/连拍照片是 MPO，Pillow 报的 format 是 `MPO` 不是 `JPEG`，漏了会让手机原图上传直接 400（实测踩到）。存量封面用 `manage.py recompress_covers`（默认 dry-run，`--apply` 写回；可反复执行）重压，实测 12 篇 16.47MB → 3.01MB（省 81.7%，单张 1406KB → 257KB）。
- **上传端点现在会校验「图片实际格式 vs 扩展名」**（此前只查扩展名白名单）：塞 JPEG 字节进 `.png` 会被 400 挡下。另外 `_process_cover` 读完必须 `seek(0)`，别把 `UploadedFile` 留在 EOF（同一对象可能被复用，第二次会读到空字节报「封面无法解析」）。
- 导入锁用缓存 `SET NX`（**不是** `select_for_update`：SQLite 上它是静默空操作），缓存不可用时 fail-closed 返回 503；且顺序必须是**取锁 → 限流 → 最后消费 `staged_id`**，否则被 429/409 挡住时暂存包已作废，用户白传 1GB。
- 判断封面是否需要方向校正必须看 `Orientation` **标签值**：Pillow 12.x 在无 Orientation 时 `exif_transpose` 也返回副本，用"对象是否相同"判定会给每张封面假阳告警（实测）。
- **默认分类/标签机制**（`articles/defaults.py`）：创建文章时未填分类/标签（含 `0`/空串占位值）自动挂默认分类 `default-category`（名称"默认分类"）与默认标签 `default-tag`（名称"默认标签"）；`AppConfig.ready()` 启动时 `ensure_defaults()` 幂等创建，pytest/mypy 进程内跳过（`sys.modules` 判断）、迁移期捕获 `DatabaseError`。默认分类/标签按 slug 受删除保护（DELETE 返回 400）。
- multipart 下"无分类/标签"的占位值（`''`/`'0'`/`'null'`/非正数）必须归一化为 `None`/`[]`（`articles/schemas.py` `_normalize_category_id`/`_normalize_tag_ids`），否则 `category_id=0` 会触发外键 `IntegrityError`；创建时引用不存在的分类/标签返回 400（"分类不存在"/"标签不存在"）。
- `create_article` 的 `IntegrityError` 不能一律当成 slug 冲突：只有同 slug 记录存在时才报"slug 已存在"（此时会加 `-2` 后缀重试），否则报通用创建失败；插入失败会清理已落盘的 cover/attachment，避免孤儿文件。
- **Markdown 渲染的四个坑（均实测）**：① Python-Markdown **没有 `html:False`**，原始 HTML 默认透传，**nh3 是唯一消毒边界**；② Python-Markdown 会把原始 HTML 的 `<img>`/`<a>` stash 成占位符、不进 ElementTree，所以展示属性（`loading=lazy`/`target`/`rel`）必须在**消毒后用 `html.parser` 回填**（`convert_charrefs=False`，只在 `handle_starttag` 追加属性，否则会把已转义的 `&lt;` 解回标签）；③ 表格对齐是 `style="text-align:x"`，`style` 不在白名单，需在消毒前转成 `align`；④ `Markdown.convert()` 非线程安全（gthread），必须**每请求新建实例**。
- **内联图 `store_inline_image()` 必须绕过 `default_storage.save()`**：后者遇同名会追加随机后缀（`get_available_name`），击穿内容寻址，且并发下有 TOCTOU。正确做法是 `default_storage.path()` 取**绝对路径**（相对名基准是 CWD 不是 `MEDIA_ROOT`）→ `mkdir` → 同目录临时文件写满 → `os.replace` 原子替换。**仅适用本地 `FileSystemStorage`**。
- **「正文与附件至少填一项」有三处校验**：`create`（API 层）、`update`（API 层，且**只在请求确实提交了 `content` 或附件时才判**，否则"只改 slug/标题"会被误拒）、归档导入（**planner** 层，按包内字段 ∪ 目标既有状态判最终态；不能放 `validate_package`，它不查库会误拒合法 update）。
- **HTML 导入的两个坑（均实测，来自真实便签导出）**：① `markdownify` 的 `newline_style` **必须是 `SPACES`** —— Python-Markdown 不支持 CommonMark 的行尾反斜杠硬换行，用 `BACKSLASH` 会让每行末尾渲染出字面量 `\`；② 便签导出习惯给段落加 4 个空格首行缩进，而 Markdown 里 4 个前导空格等于**代码块**（整段渲染成 `<pre><code>`），`_normalize` 因此只对「段落首行」（上一行为空）去缩进，并保留代码围栏内的缩进与行尾恰好两空格的硬换行。回归见 `tests/test_convert_html.py::TestNoteAppQuirks`。
- **文件字段（`cover_image`/`file`）不能用 `QuerySet.update()` 写**：它绕过 `Model.save()` → 不触发 `FileField.pre_save()`，上传内容既不会写入 storage，字段还会被 `get_prep_value()` 存成 `str(UploadedFile)`（客户端原始文件名），于是 `cover_image_url` 变成 `/media/<原始文件名>` 指向不存在的文件（前端图片 404）。同理 `auto_now` 的 `updated_at` 也不会刷新。`update_article` 因此走 `Model.save(update_fields=...)`，且 `update_fields` 里显式加 `updated_at`（`save(update_fields=...)` 只对列出的字段调用 `pre_save`），同时避免覆盖 `views` 等未提交字段。
- django-ninja 1.6 已移除 `ninja.pagination.Pagination`，且列表接口已改用手动分页（原 `common/pagination.py` 的 `CustomPagination` 已作为死代码删除）。
- django-ninja 的 `Schema` 内部有 `model_validator(mode='wrap')`，会把输入包装成只读 `DjangoGetter` —— 在 schema 里写 `mode='before'` 的 `model_validator` 会静默失效（无法修改值），需在 API 层处理（如 slug 自动生成）。
- Django 6 的测试 `Client.put` 默认以 `application/octet-stream` 发送且把 dict `str()` 化 —— PUT 测试须显式传 `content_type='application/x-www-form-urlencoded'` + `urlencode(data)`。
- PUT/PATCH multipart 需要 `ninja.compatibility.files.fix_request_files_middleware`（已在 `base.py` 的 MIDDLEWARE 中）。
- `templates/`、`static/` 目录当前**均不存在**（`TEMPLATES['DIRS']` 仍指向 `templates/`，仅作占位、Django 不会告警；`STATICFILES_DIRS` 已改为「目录存在才加入」以避免 `staticfiles.W004`）—— 新增模板/静态文件时创建对应目录即可。
- `docker-compose.yml` 含 4 个服务（app/redis/nginx/front），app 已通过 compose 环境注入 `REDIS_URL=redis://redis:6379/0`（redis 仅作缓存/锁，不持久化）；`prod.py` 中 PostgreSQL 仍是注释 TODO（预留，未启用）。
- **Dockerfile 的 `uv sync --frozen` 必须与 `uv.lock` 一起 `COPY`**（`COPY pyproject.toml uv.lock ./`）：只 `COPY pyproject.toml` 会导致容器内缺 lockfile，`uv sync --frozen` 直接退出码 2 构建失败；`.dockerignore` 不应排除 `uv.lock`。
- **`uv.lock` 的源是清华 TUNA 镜像**（仓库内已固化）：因此 Dockerfile **不再需要**构建期 `sed` 换源；也与本机 `~/.config/uv/uv.toml` 的默认源一致，所以 plain `uv run` 不会再重写 lock（若把 lock 换回 pypi.org，这个坑会重新出现）。
- **本机用 podman 验证部署（无 docker）；脚本同样支持 docker compose**：`podman` 5.x + `podman-compose`（`podman compose` 会转发到 `/usr/bin/podman-compose`）。流程：`scripts/blog.sh up --build`（或 `podman-compose up -d --build`）→ 访问 `http://<IP>:18888/`。`.env` 是 compose 的 `env_file` 必需项、且含机器本地密钥，因此**被 gitignore、不入库**；首次 `up` 时 `check_env_file` 会**自动从 `.env.example` 生成**一份并提示按需修改（也可提前手动 `cp .env.example .env`），`DJANGO_ENV=prod` 时必须有非空 `DJANGO_SECRET_KEY`。**不要把 `.env` 提交进仓库**（密钥/内网地址会进 git 历史，很难清干净）。
- **podman 部署的几个硬坑（均已踩过并修复）**：
  - Fedora SELinux `Enforcing` 下，bind mount **必须加 `:z`**（`./db_data:/app/db_data:z`、`nginx.conf:...:ro,z`），否则容器内 `Permission denied`。
  - `podman-compose up -d` **不会因镜像变更而重建已存在的容器**（只比镜像名）→ 改了 Dockerfile/依赖后必须 `podman-compose down && podman-compose up -d`，或至少检查容器 `Image` ID 是否等于 `latest`。
  - `RedisCache` 需要 `redis` Python 包（已加入依赖）；缺了会 `ModuleNotFoundError`，而导入锁是 fail-closed → 归档导入全 503。
  - nginx 正则里含 `{n}` 量词**必须加引号**（`location ~ "^/api/v1/admin/archives/[0-9a-f-]{36}/"`），否则 `{` 被当块定界符，nginx 启不来。
  - `.dockerignore` 必须排除 `private_archives/`：否则 `COPY . .` 把开发期归档产物打进镜像，挂空命名卷时还会被 podman 拷进卷里。
  - `podman-compose build` 首次会拉 `python:3.12-slim`/`node:22-alpine`/`nginx:1.27`/`redis:7-alpine`；本机镜像源是用户自配的 `~/.config/containers/registries.conf.d/100-dockerhub-mirrors.conf`（daocloud 优先、`docker.io` blocked），实测约 0.5～1.7 MB/s，且会瞬时抖动（重试即可），直连 docker.io 需代理（本机在 `127.0.0.1:12450`）但实测并不更快。
  - **离线/免构建部署**：`podman save --format docker-archive -m` 把 app/front/nginx/redis 四个镜像打成一个 tar，目标机 `podman load -i` 后 `podman-compose up -d`（**不加 `--build`**）。完整步骤与注意事项见 `docs/OFFLINE_IMAGE_DEPLOY.md`；注意镜像内是**代码快照**，改了代码必须重新 build + 重新导出。
  - **自制镜像已做多阶段构建（别改回单阶段）**：`Dockerfile` 的 builder 阶段装 `build-essential` + `uv` 并 `uv sync` 到 `/opt/venv`，运行阶段只 `COPY --from=builder /opt/venv`；`front/Dockerfile` 的 builder 跑 `npm ci + build`，运行阶段只带 `.output`。效果：app 683→**220MB**、front 959→**179MB**。副作用：运行阶段 `PATH` 指向 `/opt/venv/bin`，且**镜像内没有 `uv`/`gcc`**（在容器内临时装东西需自行 apt/pip）；Nuxt 的 `.output` 自包含，不需要 `node_modules`。
- **容器数据持久化**：prod 容器中 SQLite 数据库经 bind mount 存宿主机 `db_data/`（容器销毁重建不丢，首次 migrate 前需先 `mkdir -p db_data`）；`media/`、`staticfiles/` 走 named volume（app 与 nginx 共享 media）；`docker compose down` 不删数据，只有 `rm -rf db_data` 才删除数据库。
- `TEST.md` 是面向 AI 的测试用例规范文档（用于生成 pytest 用例），主体仍是历史草案，但 2026-09 迭代已补充「六、存量用例增补」（限流/黑名单/删除清理/搜索分页/头像/分类标签）并在顶部标注——仍以 `tests/` 实际代码为准。
- Git 仓库已有提交（identity 已配置为 `gkjuanmao`）；提交信息遵循 `DESIGN.md` 9.2 的规范（`feat:`/`fix:`/`docs:`/`refactor:`/`chore:` 前缀）。
