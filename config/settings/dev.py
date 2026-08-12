"""开发环境配置：继承 base，开启调试与本地缓存。"""
from .base import *  # noqa: F401, F403

# 开发环境开启调试
DEBUG = True

# 开发环境放开 Host 校验，允许局域网内通过任意 IP 访问（如 http://192.168.x.x:8000）
ALLOWED_HOSTS = ['*']

# 开发环境放开跨域限制，允许局域网前端（如 Vite 的 http://<LAN_IP>:5173）跨域调用接口
CORS_ALLOW_ALL_ORIGINS = True

SECRET_KEY = 'django-insecure-dev-key-change-me'

# 开发环境使用内存缓存
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}
