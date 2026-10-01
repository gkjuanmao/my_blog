"""博客文章相关数据结构：请求与响应 Schema。"""
import json
from datetime import datetime
from typing import Any

from django.utils import timezone
from ninja import Schema
from pydantic import field_validator

from .models import Article


def _normalize_category_id(value: Any) -> Any:
    """multipart 占位值（空串/'0'/'null'/非正数）视为未填分类。"""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if text in ('', '0', 'null', 'None', 'undefined'):
            return None
        try:
            number = int(text)
        except ValueError:
            return text
    elif isinstance(value, bool):
        return None
    else:
        number = value
    if isinstance(number, int) and number <= 0:
        return None
    return number


def _normalize_tag_ids(value: Any) -> Any:
    """兼容 multipart 下多种 tag_ids 编码：空串、JSON 数组串、逗号分隔、重复字段；
    过滤 0/负数等占位值。"""
    if value is None:
        return value
    items: list[Any]
    if isinstance(value, str):
        text = value.strip()
        if text == '':
            return []
        if text.startswith('['):
            try:
                items = json.loads(text)
            except json.JSONDecodeError:
                raise ValueError('tag_ids 格式错误') from None
        else:
            items = [int(part) for part in text.split(',') if part.strip() != '']
    elif isinstance(value, list):
        items = []
        for item in value:
            if isinstance(item, str):
                text = item.strip()
                if text == '':
                    continue
                if text.startswith('['):
                    try:
                        items.extend(json.loads(text))
                    except json.JSONDecodeError:
                        raise ValueError('tag_ids 格式错误') from None
                else:
                    items.append(int(text))
            else:
                items.append(int(item))
    elif isinstance(value, int):
        items = [value]
    else:
        return value

    result: list[int] = []
    for item in items:
        if isinstance(item, bool):
            continue
        try:
            number = int(item)
        except (TypeError, ValueError):
            raise ValueError('tag_ids 格式错误') from None
        if number > 0:
            result.append(number)
    return result


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


class CategoryIn(Schema):
    """创建分类的请求数据。"""

    name: str
    slug: str | None = None
    description: str = ''

    @field_validator('name')
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        """分类名称不能为空。"""
        name = value.strip()
        if not name:
            raise ValueError('分类名称不能为空')
        return name


class CategoryUpdateIn(Schema):
    """更新分类的请求数据，所有字段可选。"""

    name: str | None = None
    slug: str | None = None
    description: str | None = None

    @field_validator('name')
    @classmethod
    def name_not_blank(cls, value: str | None) -> str | None:
        """分类名称不能为空。"""
        if value is None:
            return None
        name = value.strip()
        if not name:
            raise ValueError('分类名称不能为空')
        return name


class TagIn(Schema):
    """创建标签的请求数据。"""

    name: str
    slug: str | None = None

    @field_validator('name')
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        """标签名称不能为空。"""
        name = value.strip()
        if not name:
            raise ValueError('标签名称不能为空')
        return name


class TagUpdateIn(Schema):
    """更新标签的请求数据，所有字段可选。"""

    name: str | None = None
    slug: str | None = None

    @field_validator('name')
    @classmethod
    def name_not_blank(cls, value: str | None) -> str | None:
        """标签名称不能为空。"""
        if value is None:
            return None
        name = value.strip()
        if not name:
            raise ValueError('标签名称不能为空')
        return name


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
    """文章详情响应：在列表基础上增加作者信息。"""

    author: str


class ArticleCreateIn(Schema):
    """创建文章的表单数据（不含文件），字段名与 design 5.3 一致。"""

    title: str
    slug: str | None = None
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


class ArchiveImportCommitIn(Schema):
    """归档导入第二阶段（commit）的请求体。"""

    staged_id: str
    strategy: str = 'skip'
    auto_create_taxonomy: bool = True
    as_draft: bool = False


class ArchiveImportPlanIn(Schema):
    """归档导入：按新策略对**已暂存**的包重新预检（不重传文件）。"""

    staged_id: str
    strategy: str = 'skip'


class BulkDeleteIn(Schema):
    """批量删除文章的请求体。"""

    ids: list[int]


class ArticleUpdateIn(Schema):
    """更新文章的表单数据（不含文件），所有字段可选。"""

    title: str | None = None
    slug: str | None = None
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
        cover_url = article.cover_image.url

    file_url = None
    if article.file:
        file_url = article.file.url

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
    """将模型实例转换为 ArticleDetailOut（含作者）。"""
    out = article_to_out(request, article).model_dump()
    return ArticleDetailOut(**out, author=article.author.username)
