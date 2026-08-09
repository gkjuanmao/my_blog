"""博客文章相关数据结构：请求与响应 Schema。"""
import json
from datetime import datetime
from typing import Any

from django.utils import timezone
from ninja import Schema
from pydantic import field_validator

from .models import Article


def _normalize_category_id(value: Any) -> Any:
    """multipart 空字符串视为未填。"""
    if isinstance(value, str) and value.strip() == '':
        return None
    return value


def _normalize_tag_ids(value: Any) -> Any:
    """兼容 multipart 下多种 tag_ids 编码：空串、JSON 数组串、逗号分隔、重复字段。"""
    if value is None:
        return value
    if isinstance(value, str):
        text = value.strip()
        if text == '':
            return []
        if text.startswith('['):
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                raise ValueError('tag_ids 格式错误') from None
        else:
            return [int(part) for part in text.split(',') if part.strip() != '']
    if isinstance(value, list):
        result: list[int] = []
        for item in value:
            if isinstance(item, str):
                text = item.strip()
                if text == '':
                    continue
                if text.startswith('['):
                    try:
                        result.extend(json.loads(text))
                    except json.JSONDecodeError:
                        raise ValueError('tag_ids 格式错误') from None
                else:
                    result.append(int(text))
            else:
                result.append(int(item))
        return result
    return value


class CategoryOut(Schema):
    """分类响应。"""

    id: int
    name: str
    slug: str
    description: str


class TagOut(Schema):
    """标签响应。"""

    id: int
    name: str
    slug: str


class ArticleOut(Schema):
    """文章列表响应：不含正文，附文件完整访问 URL。"""

    id: int
    title: str
    slug: str
    summary: str
    publish_time: datetime
    location: str
    category: CategoryOut | None = None
    tags: list[TagOut] = []
    cover_image_name: str
    cover_image_url: str | None = None
    file_name: str
    file_url: str | None = None
    is_published: bool
    views: int
    created_at: datetime
    updated_at: datetime


class ArticleDetailOut(ArticleOut):
    """文章详情响应：在列表基础上增加正文与作者信息。"""

    content: str
    author: str


class ArticleCreateIn(Schema):
    """创建文章的表单数据（不含文件），字段名与 design 5.3 一致。"""

    title: str
    slug: str | None = None
    content: str
    summary: str = ''
    publish_time: datetime
    location: str = ''
    category_id: int | None = None
    tag_ids: list[int] = []
    is_published: bool = False

    @field_validator('publish_time')
    @classmethod
    def ensure_aware(cls, value: datetime) -> datetime:
        """将 naive 时间转为当前时区（Asia/Shanghai）的 aware 时间。"""
        if timezone.is_naive(value):
            return timezone.make_aware(value)
        return value

    @field_validator('category_id', mode='before')
    @classmethod
    def normalize_category_id(cls, value: Any) -> Any:
        """multipart 空字符串视为未填。"""
        return _normalize_category_id(value)

    @field_validator('tag_ids', mode='before')
    @classmethod
    def normalize_tag_ids(cls, value: Any) -> Any:
        """兼容 multipart 下 tag_ids 的多种编码。"""
        return _normalize_tag_ids(value)


class ArticleUpdateIn(Schema):
    """更新文章的表单数据（不含文件），所有字段可选。"""

    title: str | None = None
    slug: str | None = None
    content: str | None = None
    summary: str | None = None
    publish_time: datetime | None = None
    location: str | None = None
    category_id: int | None = None
    tag_ids: list[int] | None = None
    is_published: bool | None = None

    @field_validator('publish_time')
    @classmethod
    def ensure_aware(cls, value: datetime | None) -> datetime | None:
        """将 naive 时间转为当前时区（Asia/Shanghai）的 aware 时间。"""
        if value is not None and timezone.is_naive(value):
            return timezone.make_aware(value)
        return value

    @field_validator('category_id', mode='before')
    @classmethod
    def normalize_category_id(cls, value: Any) -> Any:
        """multipart 空字符串视为未填。"""
        return _normalize_category_id(value)

    @field_validator('tag_ids', mode='before')
    @classmethod
    def normalize_tag_ids(cls, value: Any) -> Any:
        """兼容 multipart 下 tag_ids 的多种编码。"""
        return _normalize_tag_ids(value)


def article_to_out(request, article: Article) -> ArticleOut:
    """将模型实例转换为 ArticleOut，拼接文件的完整访问 URL。"""
    cover_url = None
    if article.cover_image:
        cover_url = request.build_absolute_uri(article.cover_image.url)

    file_url = None
    if article.file:
        file_url = request.build_absolute_uri(article.file.url)

    category_obj = article.category
    category = None
    if category_obj is not None:
        category = CategoryOut(
            id=category_obj.id,
            name=category_obj.name,
            slug=category_obj.slug,
            description=category_obj.description,
        )

    return ArticleOut(
        id=article.id,
        title=article.title,
        slug=article.slug,
        summary=article.summary,
        publish_time=article.publish_time,
        location=article.location,
        category=category,
        tags=[TagOut(id=t.id, name=t.name, slug=t.slug) for t in article.tags.all()],
        cover_image_name=article.cover_image_name,
        cover_image_url=cover_url,
        file_name=article.file_name,
        file_url=file_url,
        is_published=article.is_published,
        views=article.views,
        created_at=article.created_at,
        updated_at=article.updated_at,
    )


def article_to_detail(request, article: Article) -> ArticleDetailOut:
    """将模型实例转换为 ArticleDetailOut（含正文与作者）。"""
    out = article_to_out(request, article).model_dump()
    return ArticleDetailOut(**out, content=article.content, author=article.author.username)
