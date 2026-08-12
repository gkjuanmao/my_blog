# 个人博客后端项目 - 系统设计文档

> **项目名称**：My Blog Backend  
> **架构模式**：前后端分离 (API 驱动)  
> **文档版本**：v1.5  
> **最后更新**：2026-08-12  

---

## 一、项目概述

### 1.1 项目定位

基于 Python + Django 构建的**个人博客后端系统**，以纯 JSON API 形式为前端（Vue/React/Next.js）提供数据服务。后端同时保留 Django Admin 作为内容管理后台（CMS），供博主本人进行文章创作、文件管理等操作。

### 1.2 设计原则

| 原则 | 说明 |
| :--- | :--- |
| **单体优先** | 不做微服务拆分，Django 单体足以支撑个人博客流量 |
| **不过度设计** | 初期不引入 Celery、Elasticsearch 等重型组件 |
| **约定大于配置** | 统一响应格式、统一分页、统一异常处理 |
| **易迁移** | 文件存储抽象化，数据库可随时从 SQLite 切换至 PostgreSQL |
| **AI 友好** | 目录结构扁平、命名语义化，便于 AI 工具理解和生成代码 |

### 1.3 核心功能清单

- [x] 博客文章 CRUD（含 Markdown 正文、封面图、附件文件）
- [x] 分类 / 标签管理
- [x] 按标题搜索文章
- [x] JWT 身份认证
- [x] 文件本地存储（支持未来迁移至 OSS）
- [x] Django Admin 后台管理
- [x] Docker 一键部署

---

## 二、技术栈

### 2.1 核心依赖

| 类别 | 技术选型 | 版本 | 用途 |
| :--- | :--- | :--- | :--- |
| 语言 | Python | 3.12+ | 开发语言 |
| Web 框架 | Django | 6.x | 核心框架 |
| API 框架 | Django Ninja | latest | RESTful API 构建 |
| 数据校验 | Pydantic (Ninja 内置) | v2.x | 请求/响应序列化 |
| 数据库 | SQLite (开发) / PostgreSQL (生产) | - | 数据持久化 |
| 认证 | django-ninja-jwt | latest | JWT Token 签发与校验（兼容 SIMPLE_JWT 配置键） |
| 跨域 | django-cors-headers | latest | 处理前后端跨域 |
| 后台美化 | django-unfold | latest | Admin 现代化 UI |
| 图像处理 | Pillow | latest | ImageField 支持 |
| 包管理 | uv | latest | 依赖管理与虚拟环境 |
| 代码规范 | Ruff | latest | Lint |
| 类型检查 | MyPy + django-stubs | latest | 静态类型分析 |

### 2.2 部署依赖

| 类别 | 技术选型 | 用途 |
| :--- | :--- | :--- |
| WSGI 服务器 | Gunicorn | 运行 Django 应用 |
| 反向代理 | Nginx | 静态文件托管、HTTPS、负载均衡 |
| 容器化 | Docker + Docker Compose | 环境隔离与一键部署 |

---

## 三、目录结构

```text
my_blog/                          # 项目根目录 (Git 仓库根)
│
├── config/                       # Django 项目配置
│   ├── __init__.py
│   ├── settings/
│   │   ├── __init__.py           # 根据环境变量动态导入 dev/prod
│   │   ├── base.py              # 基础配置
│   │   ├── dev.py               # 开发环境 (DEBUG=True, SQLite)
│   │   └── prod.py             # 生产环境 (DEBUG=False, PostgreSQL)
│   ├── urls.py                  # 全局路由 (admin + api)
│   ├── wsgi.py
│   └── asgi.py
│
├── common/                       # 全局公共模块
│   ├── __init__.py
│   ├── responses.py             # 统一响应格式封装
│   ├── exceptions.py            # 全局异常处理器
│   ├── pagination.py            # 统一分页器
│   └── utils.py                 # 工具函数
│
├── users/                        # 用户与认证 App
│   ├── migrations/
│   ├── __init__.py
│   ├── apps.py
│   ├── models.py                # 自定义 User 模型
│   ├── schemas.py               # 登录/Token/UserOut
│   ├── api.py                   # /login, /token/refresh, /me
│   ├── authentication.py        # JWT Bearer 认证类
│   └── admin.py
│
├── articles/                     # 博客文章 App (核心业务)
│   ├── migrations/
│   ├── __init__.py
│   ├── apps.py
│   ├── models.py                # Article, Category, Tag
│   ├── schemas.py               # 文章相关 Schema
│   ├── api.py                   # 文章/分类/标签/搜索接口
│   ├── admin.py                 # Django Admin 配置
│   └── tests.py
│
├── media/                        # 用户上传文件 (本地存储)
│   ├── covers/                  # 文章封面图片
│   ├── files/                   # 文章附件文件
│   └── avatars/                 # 用户头像
│
├── docker/                       # Docker 配置
│   ├── nginx/
│   │   └── nginx.conf
│   └── entrypoint.sh
│
├── .env                          # 环境变量 (不提交 Git)
├── .env.example                  # 环境变量模板
├── .gitignore
├── pyproject.toml                # 项目元数据 + 依赖 + Ruff/MyPy 配置
├── uv.lock                       # 依赖锁定文件
├── Dockerfile
├── docker-compose.yml
├── manage.py
└── README.md
```

---

## 四、数据模型设计

### 4.1 用户模型 (users.User)

| 字段 | 类型 | 约束 | 说明 |
| :--- | :--- | :--- | :--- |
| id | BigAutoField | PK | 主键 |
| username | CharField(150) | unique, not null | 用户名 |
| email | EmailField | unique | 邮箱 |
| password | CharField | not null | 加密密码 (Django 自动处理) |
| avatar | ImageField | blank=True, null=True | 头像，upload_to: `avatars/%Y/%m/UUID.ext` |
| avatar_name | CharField(255) | blank=True | 头像原始文件名 |
| is_staff | BooleanField | default=False | 是否为管理员 |
| date_joined | DateTimeField | auto_now_add | 注册时间 |

### 4.2 博客文章 (articles.Article)

| 字段 | 类型 | 约束 | 说明 |
| :--- | :--- | :--- | :--- |
| id | BigAutoField | PK | 主键 |
| title | CharField(200) | db_index=True | 文章标题 |
| slug | SlugField(200) | unique, db_index=True | URL 别名 |
| content | TextField | not null | Markdown 正文 |
| summary | CharField(500) | blank=True | 摘要 (用于列表展示) |
| publish_time | DateTimeField | db_index=True | 发布时间 |
| location | CharField(255) | blank=True | 写作/事件地点 |
| cover_image | ImageField | not null | 封面图片，upload_to: `covers/%Y/%m/UUID.ext` |
| cover_image_name | CharField(255) | not null | 封面原始文件名 |
| file | FileField | not null | 附件文件，upload_to: `files/%Y/%m/UUID.ext` |
| file_name | CharField(255) | not null | 附件原始文件名 |
| author | ForeignKey(User) | on_delete=CASCADE | 作者 |
| category | ForeignKey(Category) | on_delete=SET_NULL, null=True | 所属分类 |
| tags | ManyToManyField(Tag) | blank=True | 标签 (多对多) |
| is_published | BooleanField | default=False | 是否发布 |
| views | PositiveIntegerField | default=0 | 阅读量 |
| created_at | DateTimeField | auto_now_add | 创建时间 |
| updated_at | DateTimeField | auto_now | 更新时间 |

### 4.3 分类 (articles.Category)

| 字段 | 类型 | 约束 | 说明 |
| :--- | :--- | :--- | :--- |
| id | BigAutoField | PK | 主键 |
| name | CharField(100) | not null | 分类名称 |
| slug | SlugField(100) | unique | URL 别名 |
| description | CharField(255) | blank=True | 分类描述 |

### 4.4 标签 (articles.Tag)

| 字段 | 类型 | 约束 | 说明 |
| :--- | :--- | :--- | :--- |
| id | BigAutoField | PK | 主键 |
| name | CharField(100) | not null | 标签名称 |
| slug | SlugField(100) | unique | URL 别名 |

---

## 五、API 接口设计

### 5.1 全局约定

- **Base URL**：`/api/v1/`
- **数据格式**：JSON
- **文件上传**：`multipart/form-data`
- **认证方式**：请求头 `Authorization: Bearer <access_token>`

#### 统一响应格式

```json
// 成功
{
  "code": 200,
  "message": "success",
  "data": { ... }
}

// 失败
{
  "code": 400,
  "message": "错误描述",
  "data": null
}

// 分页列表
{
  "code": 200,
  "message": "success",
  "data": {
    "items": [...],
    "total": 50,
    "page": 1,
    "page_size": 10
  }
}
```

### 5.2 接口清单

#### 认证模块 (users)

| 方法 | 路径 | 认证 | 说明 |
| :--- | :--- | :--- | :--- |
| POST | `/api/v1/login/` | ❌ | 用户名密码登录，返回 access + refresh token |
| POST | `/api/v1/token/refresh/` | ❌ | 刷新 access token |
| GET | `/api/v1/me/` | ✅ | 获取当前用户信息 |

#### 文章模块 (articles) - 公开接口

| 方法 | 路径 | 认证 | 说明 |
| :--- | :--- | :--- | :--- |
| GET | `/api/v1/categories/` | ❌ | 获取所有分类 |
| GET | `/api/v1/tags/` | ❌ | 获取所有标签 |
| GET | `/api/v1/articles/` | ❌ | 文章列表 (分页, 可按 category_slug 过滤) |
| GET | `/api/v1/articles/{slug}/` | ❌ | 文章详情 (views +1) |
| GET | `/api/v1/articles/search/?keyword=xxx` | ❌ | 按标题关键词搜索 |

#### 文章模块 (articles) - 管理接口

| 方法 | 路径 | 认证 | 说明 |
| :--- | :--- | :--- | :--- |
| GET | `/api/v1/admin/articles/` | ✅ | 文章列表 (含未发布草稿，分页，可按 `is_published`/`keyword`/`category_slug` 过滤) |
| POST | `/api/v1/admin/articles/` | ✅ | 创建文章 (含封面+附件上传) |
| PUT | `/api/v1/admin/articles/{id}/` | ✅ | 更新文章 |
| DELETE | `/api/v1/admin/articles/{id}/` | ✅ | 按 id 删除文章 (含草稿) |
| DELETE | `/api/v1/admin/articles/slug/{slug}/` | ✅ | 按 slug 删除文章 (含草稿) |
| POST | `/api/v1/admin/categories/` | ✅ | 创建分类 (slug 可省略，自动生成+冲突后缀) |
| GET | `/api/v1/admin/categories/{id}/` | ✅ | 分类详情 |
| PUT | `/api/v1/admin/categories/{id}/` | ✅ | 更新分类 (slug 省略保留原值) |
| DELETE | `/api/v1/admin/categories/{id}/` | ✅ | 删除分类 (其文章 category 置空；默认分类不可删除) |
| POST | `/api/v1/admin/tags/` | ✅ | 创建标签 (slug 可省略，自动生成+冲突后缀) |
| GET | `/api/v1/admin/tags/{id}/` | ✅ | 标签详情 |
| PUT | `/api/v1/admin/tags/{id}/` | ✅ | 更新标签 (slug 省略保留原值) |
| DELETE | `/api/v1/admin/tags/{id}/` | ✅ | 删除标签 (仅解除 M2M 关联；默认标签不可删除) |

### 5.3 核心接口详细定义

> **总则**
> - 成功响应统一为信封 `{"code": <HTTP状态码>, "message": "success", "data": {...}}`；创建类接口返回 201。
> - 业务错误（`HttpError`，如 400/401/404）同样返回信封，`code` 与 HTTP 状态码一致、`data` 恒为 `null`、`message` 为中文错误描述。
> - **参数校验失败**（必填缺失、格式错误、空白名称、非法分页值等，由 Pydantic 拦截）返回 **422**，响应体为 `{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}`，不走统一信封。
> - 未认证访问管理接口（未携带或无效的 `Authorization: Bearer <token>`）返回 401。
> - 分页列表接口的 `data` 结构固定为 `{"items": [...], "total": int, "page": int, "page_size": int}`；`page` 默认 1（≥1），`page_size` 默认 10（1~100），非法取值返回 422。

#### 文章响应数据结构

**列表项 `ArticleOut`**（列表/搜索/创建/更新共用）：
```json
{
  "id": 1,
  "title": "我的第一篇博客",
  "slug": "my-first-post",
  "summary": "这是摘要...",
  "publish_time": "2026-08-09T14:00:00Z",
  "location": "北京",
  "category": { "id": 1, "name": "默认分类", "slug": "default-category", "description": "" },
  "tags": [ { "id": 1, "name": "默认标签", "slug": "default-tag" } ],
  "cover_image_name": "封面.jpg",
  "cover_image_url": "http://localhost:8000/media/covers/2026/08/a1b2c3.jpg",
  "file_name": "附件.pdf",
  "file_url": "http://localhost:8000/media/files/2026/08/d4e5f6.pdf",
  "is_published": true,
  "views": 0,
  "created_at": "2026-08-09T10:30:00Z",
  "updated_at": "2026-08-09T10:30:00Z"
}
```

**详情 `ArticleDetailOut`** = 上述结构 + 正文与作者：`"content": "## 正文\n\nMarkdown 内容...", "author": "admin"`。

---

### 5.3.1 认证模块 (users)

#### POST `/api/v1/login/` (登录)

**请求**：`Content-Type: application/json`

| 参数      | 类型   | 必填 | 说明     |
| :------ | :--- | :- | :----- |
| username | string | ✅  | 用户名   |
| password | string | ✅  | 密码     |

**响应** (200)：
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "access": "eyJhbGciOiJIUzI1NiIs...",
    "refresh": "eyJhbGciOiJIUzI1NiIs..."
  }
}
```

**错误**：
- 401：「用户名或密码错误」（信封格式）
- 422：缺少 `username`/`password` 或为空（`detail` 格式）

#### POST `/api/v1/token/refresh/` (刷新访问令牌)

**请求**：`Content-Type: application/json`

| 参数      | 类型   | 必填 | 说明       |
| :------ | :--- | :- | :------- |
| refresh | string | ✅  | refresh token |

**响应** (200)：
```json
{
  "code": 200,
  "message": "success",
  "data": { "access": "eyJhbGciOiJIUzI1NiIs..." }
}
```

**错误**：
- 401：「refresh 令牌无效或已过期」（信封格式）
- 422：缺少 `refresh`（`detail` 格式）

#### GET `/api/v1/me/` (当前用户信息)

**认证**：✅ `Authorization: Bearer <access_token>`

**响应** (200)：
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "id": 1,
    "username": "admin",
    "email": "admin@example.com",
    "avatar": "avatars/2026/08/12/a1b2c3d4.jpg",
    "avatar_name": "头像.jpg",
    "date_joined": "2026-08-09T10:30:00Z"
  }
}
```

> `avatar` 为媒体相对路径，未上传头像时为 `null`；`avatar_name` 为头像原始文件名，未上传时为空串。

**错误**：
- 401：未携带 / Token 格式错误（「无效」）/ Token 过期（「过期」），均为信封格式

---

### 5.3.2 文章模块 · 公开接口 (articles)

#### GET `/api/v1/categories/` (分类列表)

**认证**：❌　**响应** (200)：
```json
{
  "code": 200,
  "message": "success",
  "data": [
    { "id": 1, "name": "默认分类", "slug": "default-category", "description": "" }
  ]
}
```

#### GET `/api/v1/tags/` (标签列表)

**认证**：❌　**响应** (200)：
```json
{
  "code": 200,
  "message": "success",
  "data": [
    { "id": 1, "name": "默认标签", "slug": "default-tag" }
  ]
}
```

#### GET `/api/v1/articles/` (文章列表)

**认证**：❌　仅返回已发布文章。

| 参数 | 类型 | 必填 | 说明 |
| :--- | :--- | :- | :--- |
| page | int | ❌ | 页码，默认 1，≥1 |
| page_size | int | ❌ | 每页数量，默认 10，1~100 |
| category_slug | string | ❌ | 按分类别名过滤 |

**响应** (200)：
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "items": [ { "id": 1, "title": "我的第一篇博客", "slug": "my-first-post", "summary": "这是摘要...", "publish_time": "2026-08-09T14:00:00Z", "location": "北京", "category": null, "tags": [], "cover_image_name": "封面.jpg", "cover_image_url": "http://localhost:8000/media/covers/2026/08/a1b2c3.jpg", "file_name": "附件.pdf", "file_url": "http://localhost:8000/media/files/2026/08/d4e5f6.pdf", "is_published": true, "views": 0, "created_at": "2026-08-09T10:30:00Z", "updated_at": "2026-08-09T10:30:00Z" } ],
    "total": 1,
    "page": 1,
    "page_size": 10
  }
}
```

**错误**：422：`page`/`page_size` 非法取值（如 `page=0`，`detail` 格式）

#### GET `/api/v1/articles/{slug}/` (文章详情)

**认证**：❌　仅返回已发布文章，访问后 `views` +1。

**响应** (200)：`data` 为 `ArticleDetailOut`（见上文结构，含 `content`、`author`）。

**错误**：404：「文章不存在」（信封格式）

#### GET `/api/v1/articles/search/` (搜索文章)

**认证**：❌　按标题模糊搜索已发布文章，返回数组（非分页）。

| 参数 | 类型 | 必填 | 说明 |
| :--- | :--- | :- | :--- |
| keyword | string | ✅ | 关键词，标题模糊匹配 |

**响应** (200)：
```json
{
  "code": 200,
  "message": "success",
  "data": [
    { "id": 1, "title": "我的第一篇博客", "slug": "my-first-post", "summary": "这是摘要...", "publish_time": "2026-08-09T14:00:00Z", "location": "北京", "category": null, "tags": [], "cover_image_name": "封面.jpg", "cover_image_url": "http://localhost:8000/media/covers/2026/08/a1b2c3.jpg", "file_name": "附件.pdf", "file_url": "http://localhost:8000/media/files/2026/08/d4e5f6.pdf", "is_published": true, "views": 0, "created_at": "2026-08-09T10:30:00Z", "updated_at": "2026-08-09T10:30:00Z" }
  ]
}
```

**错误**：422：缺少 `keyword`（`detail` 格式）

---

### 5.3.3 文章模块 · 管理接口 (admin)

> 本小节所有接口均需认证 ✅：`Authorization: Bearer <access_token>`；未认证返回 401。

#### GET `/api/v1/admin/articles/` (管理文章列表)

返回全部文章（含未发布草稿）。

| 参数 | 类型 | 必填 | 说明 |
| :--- | :--- | :- | :--- |
| page | int | ❌ | 页码，默认 1，≥1 |
| page_size | int | ❌ | 每页数量，默认 10，1~100 |
| is_published | bool | ❌ | 按发布状态过滤 |
| keyword | string | ❌ | 标题关键词模糊搜索 |
| category_slug | string | ❌ | 按分类别名过滤 |

**响应** (200)：`data` 结构与公开 `GET /articles/` 一致（`items` 为 `ArticleOut` 数组 + `total`/`page`/`page_size`）。

#### POST `/api/v1/admin/articles/` (创建文章)

**请求**：`Content-Type: multipart/form-data`

| 参数 | 类型 | 必填 | 说明 |
| :--- | :--- | :- | :--- |
| title | string | ✅ | 标题 |
| slug | string | ❌ | URL 别名；不传则从 title 自动生成 (中文转拼音)，冲突自动加后缀 (如 `xxx-2`) |
| content | string | ✅ | Markdown 正文 |
| summary | string | ❌ | 摘要 |
| publish_time | string (ISO 8601) | ✅ | 发布时间，如 `2026-08-09T14:00:00Z` |
| location | string | ❌ | 地点 |
| category_id | int | ❌ | 分类 ID；不传/`0` 视为未填，自动使用默认分类 (`default-category`) |
| tag_ids | array[int] | ❌ | 标签 ID 列表；不传/`0` 视为未填，自动使用默认标签 (`default-tag`) |
| is_published | bool | ❌ | 是否发布 (默认 false) |
| cover | File (image) | ✅ | 封面图片 (JPG/PNG/Webp, ≤20MB) |
| attachment | File | ✅ | 附件文件 (PDF/DOCX, ≤50MB) |

> **默认分类/标签机制**：创建文章时若未填 `category_id`/`tag_ids`（含 `''`/`'0'`/`'null'` 等占位值），自动挂载默认分类 `default-category`（名称"默认分类"）与默认标签 `default-tag`（名称"默认标签"），确保每个新建文章都有分类与标签。默认数据由服务启动时 `AppConfig.ready()` 幂等创建；引用不存在的分类/标签返回 400（"分类不存在"/"标签不存在"）。

**响应** (201)：`data` 为完整 `ArticleOut`（`code` 为 201）。

**错误**：
- 400：「封面仅支持 JPG/PNG/WebP 格式」「封面大小不能超过 20MB」「附件仅支持 PDF/Word 格式」「附件大小不能超过 50MB」「分类不存在」「标签不存在」「slug 冲突过多」「创建失败：请检查分类/标签等参数是否正确」（信封格式）
- 422：缺少必填字段（如 `title`/`content`/`publish_time`/`cover`/`attachment`）或 `tag_ids` 格式错误（`detail` 格式）

#### PUT `/api/v1/admin/articles/{id}/` (更新文章)

**请求**：`Content-Type: multipart/form-data`，所有字段可选；`cover`/`attachment` 不传则保留原文件。

| 参数 | 类型 | 说明 |
| :--- | :--- | :--- |
| title / content / summary / location / publish_time / is_published | 同创建 | 传入才更新，`publish_time` 为 ISO 8601 |
| slug | string | 不传保留原值；传入则自动去重（冲突加后缀，`exclude_id` 排除自身） |
| category_id | int | 传入才更新；引用不存在的分类返回 400「分类不存在」 |
| tag_ids | array[int] | 传入才更新（覆盖标签）；引用不存在返回 400「标签不存在」 |
| cover / attachment | File | 传入才替换，校验同创建 |

**响应** (200)：`data` 为完整 `ArticleOut`。

**错误**：
- 404：「文章不存在」
- 400：「分类不存在」「标签不存在」「slug 已存在」「更新失败：请检查分类/标签等参数是否正确」（信封格式）
- 422：字段格式非法（`detail` 格式）

#### DELETE `/api/v1/admin/articles/{id}/` (按 id 删除)

删除指定文章（含草稿），同时清理其封面与附件文件。

**响应** (200)：
```json
{ "code": 200, "message": "删除成功", "data": null }
```

**错误**：404：「文章不存在」

#### DELETE `/api/v1/admin/articles/slug/{slug}/` (按 slug 删除)

**响应** (200)：同按 id 删除（`message` 为「删除成功」，`data` 为 `null`）。

**错误**：404：「文章不存在」

#### POST `/api/v1/admin/categories/` (创建分类)

**请求**：`Content-Type: application/json`

| 参数 | 类型 | 必填 | 说明 |
| :--- | :--- | :- | :--- |
| name | string | ✅ | 分类名称，不能为空 |
| slug | string | ❌ | 别名；不传则从 name 自动生成 (中文转拼音)，冲突自动加后缀 |
| description | string | ❌ | 描述，默认空串 |

**响应** (201)：
```json
{ "code": 201, "message": "success", "data": { "id": 1, "name": "技术", "slug": "tech", "description": "" } }
```

**错误**：422：缺少 `name` 或名称为空白（`detail` 格式）

#### GET `/api/v1/admin/categories/{id}/` (分类详情)

**响应** (200)：`data` 为 `CategoryOut`（`id`/`name`/`slug`/`description`）。

**错误**：404：「分类不存在」

#### PUT `/api/v1/admin/categories/{id}/` (更新分类)

**请求**：`Content-Type: application/json`，所有字段可选；`slug` 省略时保留原值。

| 参数 | 类型 | 说明 |
| :--- | :--- | :--- |
| name | string | 传入才更新，不能为空 |
| slug | string | 传入才更新，自动去重（排除自身） |
| description | string | 传入才更新 |

**响应** (200)：`data` 为 `CategoryOut`。

**错误**：
- 404：「分类不存在」
- 400：「slug 已存在」（信封格式）
- 422：名称为空白（`detail` 格式）

#### DELETE `/api/v1/admin/categories/{id}/` (删除分类)

删除分类，其下文章的 `category` 置空（SET_NULL），文章保留。

**响应** (200)：`{"code": 200, "message": "删除成功", "data": null}`

**错误**：
- 404：「分类不存在」
- 400：「默认分类不可删除」（默认分类 `default-category` 受删除保护，信封格式）

#### POST `/api/v1/admin/tags/` (创建标签)

**请求**：`Content-Type: application/json`

| 参数 | 类型 | 必填 | 说明 |
| :--- | :--- | :- | :--- |
| name | string | ✅ | 标签名称，不能为空 |
| slug | string | ❌ | 别名；不传则从 name 自动生成 (中文转拼音)，冲突自动加后缀 |

**响应** (201)：`{"code": 201, "message": "success", "data": {"id": 1, "name": "Python", "slug": "python"}}`

**错误**：422：缺少 `name` 或名称为空白（`detail` 格式）

#### GET `/api/v1/admin/tags/{id}/` (标签详情)

**响应** (200)：`data` 为 `TagOut`（`id`/`name`/`slug`）。

**错误**：404：「标签不存在」

#### PUT `/api/v1/admin/tags/{id}/` (更新标签)

**请求**：`Content-Type: application/json`，所有字段可选；`slug` 省略时保留原值。

**响应** (200)：`data` 为 `TagOut`。

**错误**：
- 404：「标签不存在」
- 400：「slug 已存在」（信封格式）
- 422：名称为空白（`detail` 格式）

#### DELETE `/api/v1/admin/tags/{id}/` (删除标签)

删除标签，仅解除其与文章的多对多关联，文章保留。

**响应** (200)：`{"code": 200, "message": "删除成功", "data": null}`

**错误**：
- 404：「标签不存在」
- 400：「默认标签不可删除」（默认标签 `default-tag` 受删除保护，信封格式）

---

## 六、认证方案

### 6.1 技术选型

使用 `django-ninja-jwt` 库实现 JWT 认证（其内部基于 `djangorestframework-simplejwt`，并兼容读取 `SIMPLE_JWT` 配置键，已实现于 `config/settings/base.py`）。

### 6.2 认证流程

```
┌──────────┐         ┌──────────────┐         ┌──────────┐
│  前端    │  POST   │  Django 后端  │  校验   │  数据库   │
│          │ /login/ │              │ ──────▶ │  User表  │
│          │◀────────│  签发 Token  │         │          │
│  存储    │ access  │              │         │          │
│  Token   │ refresh │              │         │          │
└──────────┘         └──────────────┘         └──────────┘

┌──────────┐         ┌──────────────┐
│  前端    │  GET    │  Django 后端  │
│          │ /me/   │              │
│  Header: │────────▶│  解析 Token  │──▶ 返回用户信息
│  Bearer  │         │  校验有效期  │
│  <token> │         │              │
└──────────┘         └──────────────┘
```

### 6.3 Token 配置

```python
# config/settings/base.py
from datetime import timedelta

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=2),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
}
```

### 6.4 Ninja 认证类

继承 `ninja.security.HttpBearer`，在 `authenticate` 方法中调用 `AccessToken(token)` 解析并返回 User 对象。

---

## 七、文件存储方案

### 7.1 存储策略

| 文件类型 | 存储路径模板 | 大小限制 | 允许格式 |
| :--- | :--- | :--- | :--- |
| 文章封面 | `media/covers/%Y/%m/UUID.ext` | ≤ 20MB | JPG, PNG, Webp |
| 文章附件 | `media/files/%Y/%m/UUID.ext` | ≤ 50MB | PDF, DOCX, HTML |
| 用户头像 | `media/avatars/%Y/%m/UUID.ext` | ≤ 2MB | JPG, PNG |

### 7.2 文件命名规则

- **物理文件名**：使用 `uuid.uuid4().hex` 生成，彻底避免中文乱码和命名冲突。
- **原始文件名**：通过模型的 `xxx_name` 字段单独记录，供前端展示和下载时使用。

### 7.3 文件访问

- **开发环境**：Django 内置 `static()` 辅助函数直接托管 `/media/` 路径。
- **生产环境**：Nginx 通过 `alias` 指令直接指向 `media/` 目录，不经过 Django 进程。
- **未来扩展**：通过 `django-storages` 可无缝切换至阿里云 OSS / Cloudflare R2，业务代码零修改。

---

## 八、部署方案

### 8.1 Docker 架构

```
┌─────────────────────────────────────────────────┐
│              Docker Compose                       │
│                                                  │
│  ┌─────────┐    ┌─────────┐    ┌─────────────┐ │
│  │  Nginx  │───▶│  Web    │───▶│ PostgreSQL  │ │
│  │  :80    │    │  :8000  │    │   :5432     │ │
│  │         │    │(Gunicorn│    │             │ │
│  │ /media/ │    │ +Django)│    │             │ │
│  │ /api/   │    │         │    │             │ │
│  │ /admin/ │    │         │    │             │ │
│  └─────────┘    └─────────┘    └─────────────┘ │
│       │              │                          │
│       └──── /media/ ─┘  (共享 Volume)           │
└─────────────────────────────────────────────────┘
```

### 8.2 Nginx 路由规则

| 路径 | 处理方式 |
| :--- | :--- |
| `/api/*` | 反向代理到 `web:8000` |
| `/admin/*` | 反向代理到 `web:8000` |
| `/media/*` | 直接 alias 到本地文件目录，开启 7 天缓存 |
| `/*` | 返回 404 (前端由独立服务/CDN 托管) |

### 8.3 数据持久化

- 数据库：Docker named volume `pg_data`
- 媒体文件：Docker named volume `media_data`，同时挂载到 web 和 nginx 容器

---

## 九、开发规范

### 9.1 代码规范

- **格式化 & Lint**：Ruff（替代 Black + isort + flake8）
- **类型提示**：所有函数参数和返回值必须标注类型
- **命名约定**：
  - 模型类：`PascalCase` (如 `Article`)
  - 函数/变量：`snake_case` (如 `create_article`)
  - API 路径：`kebab-case` 或 `snake_case` (如 `/api/v1/articles/`)
  - 常量：`UPPER_SNAKE_CASE` (如 `MAX_FILE_SIZE`)

### 9.2 Git 规范

```
feat: 新增文章上传接口
fix: 修复搜索接口分页错误
docs: 更新 API 文档
refactor: 重构认证模块
chore: 升级 Django 至 6.0
```

### 9.3 .gitignore 必须包含

```
.venv/
__pycache__/
*.pyc
media/
.env
db.sqlite3
*.egg-info/
.mypy_cache/
.ruff_cache/
```

---

## 十、OpenCode 执行计划

按以下顺序逐步将 Prompt 喂给 OpenCode，每个阶段完成并验证后再进入下一阶段：

| 阶段 | 内容 | 验证标准 |
| :--- | :--- | :--- |
| **Phase 1** | 项目骨架 + Settings + common 模块 | `uv run python manage.py check` 无报错 |
| **Phase 2** | users App (模型 + JWT 认证) | 访问 `/api/docs` 可测试登录接口 |
| **Phase 3** | articles App (文章模型 + 文件上传 + 搜索) | 通过 Swagger 成功上传文件并在 media/ 目录看到文件 |
| **Phase 4** | Django Admin 配置 (django-unfold 美化) | 后台可正常管理文章/分类/标签 |
| **Phase 5** | Docker + Nginx 部署配置 | `docker-compose up` 后所有接口正常访问 |

---

## 十一、环境变量清单 (.env)

```env
# Django（环境切换，默认 dev；DJANGO_SETTINGS_MODULE 恒为 config.settings）
DJANGO_ENV=dev
DJANGO_SECRET_KEY=your-random-secret-key-here
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost

# Database (生产环境，预留)
# POSTGRES_DB=my_blog
# POSTGRES_USER=my_blog
# POSTGRES_PASSWORD=change-me
# POSTGRES_HOST=db
# POSTGRES_PORT=5432

# Cache (生产环境，预留)
# REDIS_URL=redis://redis:6379/0
```

> 注意：`.env` 仅被 docker-compose 的 `env_file` 读取；本地开发时 Django 不会自动加载 `.env`，dev 环境使用硬编码的开发密钥。JWT 密钥复用 `DJANGO_SECRET_KEY`（`SIMPLE_JWT` 未单独配置 `SIGNING_KEY`）。

---

> **文档结束**  
> 本文档作为项目开发的唯一参考源（Single Source of Truth），所有代码实现必须与本文档保持一致。如有设计变更，请先更新本文档再修改代码。
