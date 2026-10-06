from django.apps import AppConfig


class ArticlesConfig(AppConfig):
    name = 'articles'
    verbose_name = '博客文章'

    def ready(self) -> None:
        """服务启动时注册信号（删除文章时清理文件）。

        默认分类/标签改为**惰性创建**：创建文章时若未指定分类/标签，由
        ``articles/api.py`` 的 ``_resolve_category_and_tags`` 调用 ``ensure_defaults()``
        兜底。这样避免在应用初始化阶段查库（Django 6 会因此打 RuntimeWarning）。
        """
        # 信号注册与运行环境无关，必须始终生效（删除文章时清理文件）。
        from . import signals  # noqa: F401
