from django.apps import AppConfig


class UsersConfig(AppConfig):
    name = 'users'
    verbose_name = '用户'

    def ready(self) -> None:
        # 导入即注册 post_delete 信号（删除用户时清理头像文件）
        from . import signals  # noqa: F401
