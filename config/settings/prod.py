"""生产环境配置：继承 base，关闭调试并启用安全策略。

TLS/CSRF/缓存均通过环境变量开关，默认适配当前「nginx 纯 HTTP 反代 + SQLite」的
部署形态；启用 HTTPS 或 Redis 时只需设置对应环境变量，无需改代码。
PostgreSQL 配置仍预留为注释（当前 prod 实际使用 base 中的 SQLite）。
"""
import os

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

# 缓存：配置 REDIS_URL 时使用 Redis，否则回落到进程内缓存（当前 docker-compose 未含 redis）
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
