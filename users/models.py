"""自定义用户模型：继承 AbstractUser，新增头像字段。"""
import uuid
from typing import Any

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

# 头像约束（对齐 DESIGN.md 4.1 / 7.2）
AVATAR_EXTENSIONS = {'jpg', 'jpeg', 'png'}
AVATAR_MAX_SIZE = 2 * 1024 * 1024  # 2MB


def avatar_upload_path(instance: Any, filename: str) -> str:
    """头像动态路径：avatars/%Y/%m/UUID.ext。"""
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    name = f'{uuid.uuid4().hex}.{ext}' if ext else uuid.uuid4().hex
    return f'avatars/{timezone.now():%Y/%m}/{name}'


def validate_avatar(file: Any) -> None:
    """校验头像格式与大小：仅 JPG/PNG，且不超过 2MB。

    作为 ImageField validator 由表单/admin 的 full_clean 触发。
    """
    name = getattr(file, 'name', '') or ''
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    if ext not in AVATAR_EXTENSIONS:
        raise ValidationError('头像仅支持 JPG/PNG 格式')
    size = getattr(file, 'size', None)
    if size is not None and size > AVATAR_MAX_SIZE:
        raise ValidationError('头像大小不能超过 2MB')


class User(AbstractUser):
    """项目自定义用户模型，统一替换默认的 auth.User。"""

    avatar = models.ImageField(
        upload_to=avatar_upload_path,
        blank=True,
        null=True,
        validators=[validate_avatar],
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
