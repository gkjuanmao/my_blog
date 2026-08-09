"""开发环境配置：继承 base，开启调试与本地缓存。"""
from .base import *  # noqa: F401, F403

# 开发环境开启调试
DEBUG = True

ALLOWED_HOSTS = ['127.0.0.1', 'localhost']

SECRET_KEY = 'django-insecure-dev-key-change-me'

# 开发环境使用内存缓存
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}
