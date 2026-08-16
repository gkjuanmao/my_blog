"""生产环境配置：继承 base，关闭调试并启用安全策略。

PostgreSQL 与 Redis 的配置预留为注释，启用时按需取消注释并设置环境变量。
"""
import os

from .base import *  # noqa: F401, F403

# 生产环境必须关闭调试
DEBUG = False

ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', '').split(',')

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY')

if not SECRET_KEY:
    raise RuntimeError('DJANGO_SECRET_KEY must be set in production.')

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

# TODO: 生产环境使用 Redis 缓存，取消注释并设置 REDIS_URL
# CACHES = {
#     'default': {
#         'BACKEND': 'django.core.cache.backends.redis.RedisCache',
#         'LOCATION': os.environ.get('REDIS_URL', 'redis://redis:6379/0'),
#     }
# }

# 生产环境安全配置
SECURE_SSL_REDIRECT = False  # 当前 nginx :18080 纯 HTTP 反代；启用 TLS 后再打开
SESSION_COOKIE_SECURE = False  # 当前 nginx :18080 纯 HTTP；启用 TLS 后再打开
CSRF_COOKIE_SECURE = False     # 同上
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
