"""用户模型信号：删除用户时清理头像文件。"""
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import User


@receiver(post_delete, sender=User)
def delete_user_avatar(sender, instance: User, **kwargs) -> None:
    """删除用户后清理头像文件，避免 media 下残留孤儿文件。

    用 post_delete 而不是覆盖 ``Model.delete()``：这样 ``QuerySet.delete()``
    （批量删除、级联删除）与 Django admin 的删除同样会触发。
    ``FileField.delete(save=False)`` 只删 storage 里的文件并清空字段值，不写数据库；
    文件已不存在时 storage 会静默忽略。
    """
    if instance.avatar:
        instance.avatar.delete(save=False)
