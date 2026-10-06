"""生产环境配置：继承 base，关闭调试并启用安全策略。

TLS/CSRF/缓存均通过环境变量开关，默认适配「nginx 反代 + SQLite」的部署形态；
启用 HTTPS、Redis 或 PostgreSQL 时只需设置对应环境变量，无需改代码。
"""
import os
import warnings

from .base import *  # noqa: F401, F403


def _env_bool(name: str, default: bool = False) -> bool:
    """把环境变量解析为布尔值（1/true/yes/on 视为真）。"""
    return os.environ.get(name, str(default)).strip().lower() in ('1', 'true', 'yes', 'on')


def _env_list(name: str) -> list[str]:
    """把逗号分隔的环境变量解析为去空列表。"""
    return [item.strip() for item in os.environ.get(name, '').split(',') if item.strip()]


# 生产环境必须关闭调试
DEBUG = False

# 未配置时回落到本机，避免出现 ALLOWED_HOSTS=[''] 的隐式行为
ALLOWED_HOSTS = _env_list('DJANGO_ALLOWED_HOSTS') or ['localhost', '127.0.0.1']

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY')

if not SECRET_KEY:
    raise RuntimeError('DJANGO_SECRET_KEY must be set in production.')

# TLS 总开关：部署 HTTPS 后设 DJANGO_USE_TLS=true，一并打开跳转与安全 Cookie
USE_TLS = _env_bool('DJANGO_USE_TLS')
SECURE_SSL_REDIRECT = USE_TLS
SESSION_COOKIE_SECURE = USE_TLS
CSRF_COOKIE_SECURE = USE_TLS

# 反向代理后用 X-Forwarded-Proto 判断原始协议（nginx 已设置该头）
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https') if USE_TLS else None

# HSTS 仅在 HTTPS 下有意义：HTTP 部署时保持 0；启用 TLS 后按需设置
# DJANGO_SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_SECURE_HSTS_SECONDS', '0')) if USE_TLS else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
SECURE_HSTS_PRELOAD = SECURE_HSTS_SECONDS > 0

# CSRF 信任来源：Django admin 等表单接口的对外地址，如 https://blog.example.com
CSRF_TRUSTED_ORIGINS = _env_list('DJANGO_CSRF_TRUSTED_ORIGINS')

# API 文档（Swagger UI，/api/v1/docs）：生产默认关闭，需要时显式 ENABLE_API_DOCS=true 开放
ENABLE_API_DOCS = _env_bool('ENABLE_API_DOCS')

# 缓存：配置 REDIS_URL 时使用 Redis，否则回落到进程内缓存
# （docker-compose 已注入 REDIS_URL=redis://redis:6379/0；仅手工跑 prod 时才可能缺配）
REDIS_URL = os.environ.get('REDIS_URL', '')
if REDIS_URL:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': REDIS_URL,
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        }
    }
    # 重要提醒：LocMemCache 是**每进程**的。登录失败限流、归档导入锁与最小间隔
    # 都建在缓存上，多 worker（见 Dockerfile 的 --workers 3）下各自为政：
    # 锁不再能保证“单写者”，限流也会被放大到 N 倍。生产请配置 REDIS_URL。
    warnings.warn(
        'REDIS_URL 未设置：缓存回落为进程内 LocMemCache，多 worker 下导入锁/登录限流将不准确',
        RuntimeWarning,
        stacklevel=2,
    )

# 数据库：生产当前仍用 SQLite（继承 base.py，`db_data/db.sqlite3`，timeout=20）。
# SQLite 同一时刻只允许一个写者，而 gunicorn 为 3 workers × 4 threads，写入密集时
# （归档导入、批量删除）可能出现 `database is locked`；已用 timeout=20 缓解，且导入
# 走缓存锁串行化。读多写少的博客场景足够；若并发写显著增长，再切换 PostgreSQL：
# 取消下面注释、在 docker-compose.yml 增加 db 服务并设置 POSTGRES_* 环境变量。
# TODO: 生产环境使用 PostgreSQL，取消注释并按需设置环境变量
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql',
#         'NAME': os.environ.get('POSTGRES_DB', 'my_blog'),
#         'USER': os.environ.get('POSTGRES_USER', 'my_blog'),
#         'PASSWORD': os.environ.get('POSTGRES_PASSWORD', ''),
#         'HOST': os.environ.get('POSTGRES_HOST', 'db'),
#         'PORT': os.environ.get('POSTGRES_PORT', '5432'),
#     }
# }

# 生产环境安全配置
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
