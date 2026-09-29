import sys

from django.apps import AppConfig
from django.db import DatabaseError


class ArticlesConfig(AppConfig):
    name = 'articles'
    verbose_name = '博客文章'

    def ready(self) -> None:
        """服务启动时注册信号并确保默认分类/标签存在。

        仅在真实服务进程中执行：pytest 运行期与 mypy 的 django-stubs 插件初始化
        都会触发 ready()，此时跳过避免在开发库上写数据；migrate 等命令执行时
        表可能尚未创建，捕获数据库错误。
        """
        # 信号注册与运行环境无关，必须始终生效（删除文章时清理文件）。
        from . import signals  # noqa: F401

        if 'pytest' in sys.modules or 'mypy' in sys.modules:
            return
        try:
            from .defaults import ensure_defaults

            ensure_defaults()
        except DatabaseError:
            pass
