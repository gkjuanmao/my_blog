"""文章模型信号：删除时清理文件、写操作时失效公开列表缓存。"""
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .caching import invalidate_public_cache
from .models import Article, Category, Tag


@receiver(post_delete, sender=Article)
def delete_article_files(sender, instance: Article, **kwargs) -> None:
    """文章删除后清理其封面/附件文件，避免 media 下残留孤儿文件。

    用 post_delete 而非覆盖 ``Model.delete()``：这样 ``QuerySet.delete()`` 与
    Django admin 的批量删除同样会触发；``FileField.delete(save=False)`` 只删除
    storage 中的文件并清空字段值，不会再写数据库。文件已不存在时 storage 会静默忽略。
    """
    for field in (instance.cover_image, instance.file):
        if field:
            field.delete(save=False)


@receiver([post_save, post_delete], sender=Article)
@receiver([post_save, post_delete], sender=Category)
@receiver([post_save, post_delete], sender=Tag)
def invalidate_public_cache_on_write(sender, **kwargs) -> None:
    """文章/分类/标签任一写操作后使公开列表缓存立即失效。

    覆盖 API、Django admin、归档导入等所有写入路径（它们最终都走 ORM 保存/删除）。
    """
    invalidate_public_cache()
