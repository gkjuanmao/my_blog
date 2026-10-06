"""全局路由配置：admin 后台 + Django Ninja API 路由。"""
from typing import cast

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import URLResolver, path
from ninja import NinjaAPI

from articles.api import admin_router
from articles.api import router as articles_router
from common.exceptions import register_exception_handlers
from users.api import router as users_router

# 初始化 Django Ninja API
# Swagger UI 默认仅开发环境开放；生产（DEBUG=False）需显式置 ENABLE_API_DOCS=true 才开放
_docs_enabled = settings.DEBUG or getattr(settings, 'ENABLE_API_DOCS', False)
api = NinjaAPI(
    title='My Blog API',
    version='1.0.0',
    description='前后端分离博客后端接口',
    docs_url='/docs' if _docs_enabled else None,
)

# 注册全局异常处理器
register_exception_handlers(api)

# 注册各应用路由
api.add_router('', users_router)
api.add_router('', articles_router)
api.add_router('admin', admin_router)

urlpatterns: list[URLResolver] = [
    path('admin/', admin.site.urls),
    path('api/v1/', api.urls),
]

# 开发环境下提供媒体文件访问
if settings.DEBUG:
    urlpatterns += cast(
        list[URLResolver],
        static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT),
    )
