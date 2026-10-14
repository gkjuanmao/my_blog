"""Django 基础配置：所有环境共享的通用配置。"""
import os
from datetime import timedelta
from pathlib import Path

# 项目根目录（config/settings 的上级的上级）
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# 应用注册
INSTALLED_APPS = [
    'unfold',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # 第三方应用
    'corsheaders',
    'ninja',
    # JWT refresh 轮换后的旧令牌黑名单（需迁移生成表）
    'ninja_jwt.token_blacklist',
    # 自定义应用
    'articles.apps.ArticlesConfig',
    'users.apps.UsersConfig',
    'common',
]

MIDDLEWARE = [
    # CORS 中间件需放在最前，否则跨域请求头不生效
    'corsheaders.middleware.CorsMiddleware',
    # 修复 PUT/PATCH 等非 POST 请求的 multipart 文件解析
    'ninja.compatibility.files.fix_request_files_middleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # 给公开列表接口补 Cache-Control（放在最后，便于修改已生成的响应）
    'common.middleware.PublicCacheControlMiddleware',
]

# 跨域配置：默认仅允许前端开发服务器访问（Vite 默认端口）。
# dev 环境由 dev.py 的 CORS_ALLOW_ALL_ORIGINS=True 全面放开（局域网内其他设备访问无需在此登记）；
# 生产环境经 nginx 同源访问，如需额外来源请在此按需添加——不要把内网地址提交进仓库。
CORS_ALLOWED_ORIGINS = [
    'http://localhost:5173',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# 默认使用 SQLite，生产环境在 prod.py 中切换为 PostgreSQL
# timeout：SQLite 写锁等待秒数，缓解并发写入时的 database is locked
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db_data' / 'db.sqlite3',
        'OPTIONS': {'timeout': 20},
    }
}

# 自定义用户模型（users app）
AUTH_USER_MODEL = 'users.User'

# JWT Token 配置（django-ninja-jwt 兼容读取 SIMPLE_JWT）
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=2),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    # 轮换后把旧 refresh token 加入黑名单，防止其继续可用（依赖上方 token_blacklist app）
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'zh-hans'

TIME_ZONE = 'Asia/Shanghai'

USE_I18N = True

USE_TZ = True

STATIC_URL = 'static/'

# 全局静态文件目录：目录不存在时不加入，避免 manage.py check 报 staticfiles.W004
STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').is_dir() else []

# 生产环境 collectstatic 的输出目录
STATIC_ROOT = BASE_DIR / 'staticfiles'

# 媒体文件（用户上传）配置
MEDIA_URL = '/media/'

MEDIA_ROOT = BASE_DIR / 'media'

# 阅读量去重窗口（秒）：同一 IP 对同一篇文章在该窗口内只计一次阅读
ARTICLE_VIEW_DEDUP_SECONDS = 3600

# ---------------------------------------------------------------------------
# 文章归档（导入 / 导出）
# 说明：以下常量一律在**调用时**经 articles.archive.limits.limits() 读取，
# 便于测试用 override_settings 收紧上限；不要把它们固化进模块级常量。
# ---------------------------------------------------------------------------

# 归档产物根目录：**不得**位于任何对外服务的静态/媒体目录下
ARCHIVE_ROOT = os.environ.get('ARCHIVE_ROOT') or str(BASE_DIR / 'private_archives')

# 上传暂存目录（默认为 None → 系统临时目录；容器内建议指向挂载卷）
FILE_UPLOAD_TEMP_DIR = os.environ.get('FILE_UPLOAD_TEMP_DIR') or None

ARCHIVE_STAGING_TTL_SECONDS = 1800  # 导入暂存有效期
ARCHIVE_TICKET_TTL_SECONDS = 300  # 下载票据有效期
ARCHIVE_IMPORT_MIN_INTERVAL_SECONDS = 60  # 同一用户两次导入的最小间隔
ARCHIVE_LOCK_TTL_SECONDS = 900  # 导入锁最长持有时间（SIGKILL 后靠它自解）

ARCHIVE_MAX_UPLOAD_BYTES = 1024**3  # 1GB（nginx 侧同限）
# 条目/解压上限已按"含 Markdown 正文与内联图"重新配平：每篇最少 2 成员
# （article.json + 封面）、最多 53 成员（+ 附件 + 50 张内联图），加固定成员
# manifest.json + README.md 共 2 个。见 docs/ARTICLE_MARKDOWN_PLAN.md §7.6。
ARCHIVE_MAX_ENTRIES = 2000
ARCHIVE_MAX_TOTAL_UNCOMPRESSED = 1024**3
ARCHIVE_MAX_MEMBER_BYTES = 50 * 1024**2
ARCHIVE_MAX_COMPRESSION_RATIO = 100
ARCHIVE_MAX_PATH_LENGTH = 255
ARCHIVE_MAX_DEPTH = 5
# 正文上限 200k 字符（UTF-8 最多约 600KB）经 JSON 转义后仍有余量
ARCHIVE_MAX_JSON_BYTES = 2 * 1024**2
ARCHIVE_MAX_ARTICLES_PER_EXPORT = 1000
ARCHIVE_MAX_IDS_PER_REQUEST = 200
ARCHIVE_MAX_NEW_CATEGORIES = 50
ARCHIVE_MAX_NEW_TAGS = 50
ARCHIVE_MAX_IMAGE_PIXELS = 80_000_000

# 文章 Markdown 正文长度上限（后端显式校验；ninja 的 Form 不会自动执行 max_length）
ARTICLE_CONTENT_MAX_CHARS = 200_000

# 正文内联图片（Markdown 插图）：上传 → 服务端压成 WebP → 内容寻址落盘
INLINE_IMAGE_DIR = 'inline'  # MEDIA_ROOT 下的子目录
INLINE_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}
INLINE_IMAGE_MAX_BYTES = 10 * 1024**2  # 上传源文件上限
INLINE_IMAGE_OUTPUT_BYTES = 8 * 1024**2  # 压缩后上限
INLINE_IMAGE_MAX_LONG_EDGE = 1920  # 最长边上限（只缩不放）
INLINE_IMAGE_WEBP_QUALITY = 80
INLINE_IMAGE_MAX_PIXELS = 80_000_000
INLINE_IMAGE_MAX_PER_ARTICLE = 50
INLINE_IMAGE_TRASH_DIR = '_inline_trash'  # 回收站（nginx 侧显式拒绝访问）
INLINE_IMAGE_PURGE_GRACE_HOURS = 24  # 宽限期：新文件不清理

# 后台「导入 HTML」：把手机/第三方导出的 HTML 转成 Markdown 正文。
# 走 multipart 的**文件**通道上传，因此不受 DATA_UPLOAD_MAX_MEMORY_SIZE（默认 2.5MB，
# 只约束 request.body / 表单字段）限制 —— 手机导出的 HTML 常因图片内嵌 base64 而远超它。
# 注意：nginx 必须放行更大的体积，否则会先被 nginx 以 413 拦掉。该路由走独立 location
# （`client_max_body_size 110m`），而不是调大全局 `/api/` 的 60m —— 后者会连带放宽所有普通接口。
HTML_IMPORT_MAX_BYTES = 100 * 1024**2

# 附件白名单（上传与归档共用）；html 已从上传侧移除
ATTACHMENT_EXTENSIONS = {'pdf', 'doc', 'docx'}
# 导入侧的"遗留"扩展名（决策 D23）：存量 .html 附件仍可回导，但会强制下载 + 告警
ATTACHMENT_LEGACY_EXTENSIONS = {'html'}
COVER_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}
COVER_MAX_BYTES = 20 * 1024**2
# 封面统一压成 WebP：最长边上限（只缩不放）与质量。
# 封面在详情页只是题图，原图常达 3~4MB，压缩后通常 <300KB（内网穿透省流量的关键）。
COVER_MAX_LONG_EDGE = 1600
COVER_WEBP_QUALITY = 82
COVER_OUTPUT_BYTES = 4 * 1024**2  # 压缩后上限（兜底，正常远小于此）
COVER_MAX_PIXELS = 80_000_000  # 像素数上限（防解压炸弹）
ATTACHMENT_MAX_BYTES = 50 * 1024**2

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
