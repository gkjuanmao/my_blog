"""文章模型信号：删除时同步清理 storage 中的封面与附件文件。"""
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Article


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
