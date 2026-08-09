"""自定义用户模型：继承 AbstractUser，新增头像字段。"""
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """项目自定义用户模型，统一替换默认的 auth.User。"""

    avatar = models.ImageField(
        upload_to='avatars/%Y/%m/%d/',
        blank=True,
        null=True,
        verbose_name='头像',
    )
    avatar_name = models.CharField(
        max_length=255,
        blank=True,
        verbose_name='头像原始文件名',
    )

    class Meta:
        verbose_name = '用户'
        verbose_name_plural = '用户'

    def __str__(self) -> str:
        return self.username
