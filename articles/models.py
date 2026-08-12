"""博客文章数据模型：文章、分类、标签。"""
import uuid

from django.conf import settings
from django.db import models


def _dynamic_upload_path(prefix: str, filename: str) -> str:
    """按当前年月与 UUID 生成文件存储路径，保留原始扩展名。"""
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    name = f'{uuid.uuid4().hex}.{ext}' if ext else uuid.uuid4().hex
    return f'{prefix}/{name}'


def cover_upload_path(instance, filename: str) -> str:
    """封面图片动态路径：covers/UUID.ext。"""
    return _dynamic_upload_path('covers', filename)


def file_upload_path(instance, filename: str) -> str:
    """附件动态路径：files/UUID.ext。"""
    return _dynamic_upload_path('files', filename)


class Category(models.Model):
    """文章分类。"""

    name = models.CharField(max_length=100, verbose_name='分类名称')
    slug = models.SlugField(max_length=100, unique=True, verbose_name='URL 别名')
    description = models.CharField(
        max_length=255,
        blank=True,
        verbose_name='分类描述',
    )

    class Meta:
        verbose_name = '分类'
        verbose_name_plural = '分类'
        ordering = ['name']

    def __str__(self) -> str:
        return self.name


class Tag(models.Model):
    """文章标签。"""

    name = models.CharField(max_length=100, verbose_name='标签名称')
    slug = models.SlugField(max_length=100, unique=True, verbose_name='URL 别名')

    class Meta:
        verbose_name = '标签'
        verbose_name_plural = '标签'
        ordering = ['name']

    def __str__(self) -> str:
        return self.name


class Article(models.Model):
    """博客文章，含封面图与附件文件。"""

    title = models.CharField(max_length=200, db_index=True, verbose_name='标题')
    slug = models.SlugField(max_length=200, unique=True, db_index=True, verbose_name='URL 别名')
    summary = models.CharField(max_length=500, blank=True, verbose_name='摘要')
    publish_time = models.DateTimeField(db_index=True, verbose_name='发布时间')
    location = models.CharField(max_length=255, blank=True, verbose_name='地点')
    cover_image = models.ImageField(
        upload_to=cover_upload_path,
        verbose_name='封面图片',
    )
    cover_image_name = models.CharField(max_length=255, verbose_name='封面原始文件名')
    file = models.FileField(upload_to=file_upload_path, verbose_name='附件文件')
    file_name = models.CharField(max_length=255, verbose_name='附件原始文件名')
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        verbose_name='作者',
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='所属分类',
    )
    tags = models.ManyToManyField(Tag, blank=True, verbose_name='标签')
    is_published = models.BooleanField(default=False, verbose_name='是否发布')
    views = models.PositiveIntegerField(default=0, verbose_name='阅读量')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        verbose_name = '文章'
        verbose_name_plural = '文章'
        ordering = ['-publish_time']

    def __str__(self) -> str:
        return self.title
