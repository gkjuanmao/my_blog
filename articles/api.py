"""博客文章 API：公开文章浏览与管理接口。"""
from typing import Any, cast

from django.db import IntegrityError
from django.db.models import F
from django.db.models.query import QuerySet
from django.http import HttpRequest
from ninja import File, Form, Query, Router, UploadedFile
from ninja.errors import HttpError
from ninja.responses import Status

from common.responses import success_response
from users.authentication import JWTAuth
from users.models import User

from .defaults import DEFAULT_CATEGORY_SLUG, DEFAULT_TAG_SLUG, ensure_defaults
from .models import Article, Category, Tag, cover_upload_path, file_upload_path
from .schemas import (
    ArticleCreateIn,
    ArticleUpdateIn,
    CategoryIn,
    CategoryOut,
    CategoryUpdateIn,
    TagIn,
    TagOut,
    TagUpdateIn,
    article_to_detail,
    article_to_out,
)
from .utils import generate_slug, unique_slug

router = Router(tags=['文章'])
admin_router = Router(tags=['文章管理'])

# 文件类型与大小限制
COVER_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}
ATTACHMENT_EXTENSIONS = {'pdf', 'doc', 'docx', 'html'}
COVER_MAX_SIZE = 20 * 1024 * 1024  # 20MB
ATTACHMENT_MAX_SIZE = 50 * 1024 * 1024  # 50MB

jwt_auth = JWTAuth()


def _extension(filename: str) -> str:
    """提取文件扩展名（小写，无扩展名返回空串）。"""
    return filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''


def _validate_cover(cover: UploadedFile) -> None:
    """校验封面图片格式与大小。"""
    name = cover.name or ''
    if _extension(name) not in COVER_EXTENSIONS:
        raise HttpError(400, '封面仅支持 JPG/PNG/WebP 格式')
    if (cover.size or 0) > COVER_MAX_SIZE:
        raise HttpError(400, '封面大小不能超过 20MB')


def _validate_attachment(attachment: UploadedFile) -> None:
    """校验附件格式与大小。"""
    name = attachment.name or ''
    if _extension(name) not in ATTACHMENT_EXTENSIONS:
        raise HttpError(400, '附件仅支持 PDF/Word/HTML 格式')
    if (attachment.size or 0) > ATTACHMENT_MAX_SIZE:
        raise HttpError(400, '附件大小不能超过 50MB')


def _resolve_category_and_tags(
    category_id: int | None, tag_ids: list[int]
) -> tuple[Category, list[int]]:
    """解析分类与标签：未填时使用默认值；传入但不存在时报 400。"""
    category: Category | None = None
    if category_id is None:
        category, _ = ensure_defaults()
    else:
        category = Category.objects.filter(pk=category_id).first()
        if category is None:
            raise HttpError(400, '分类不存在')

    if not tag_ids:
        _, default_tag = ensure_defaults()
        tag_ids = [default_tag.id]
    else:
        valid_ids = set(Tag.objects.filter(pk__in=tag_ids).values_list('id', flat=True))
        if len(valid_ids) != len(set(tag_ids)):
            raise HttpError(400, '标签不存在')
    return category, tag_ids  # type: ignore[return-value]


def _published_articles() -> QuerySet[Article]:
    """仅已发布且预取分类/标签的文章查询集。"""
    return Article.objects.filter(is_published=True).prefetch_related('tags', 'category')


@router.get('/categories/', response=dict)
def list_categories(request: HttpRequest) -> dict:
    """获取所有分类。"""
    categories = [
        CategoryOut(id=c.id, name=c.name, slug=c.slug, description=c.description)
        for c in Category.objects.all()
    ]
    return success_response(categories)


@router.get('/tags/', response=dict)
def list_tags(request: HttpRequest) -> dict:
    """获取所有标签。"""
    tags = [TagOut(id=t.id, name=t.name, slug=t.slug) for t in Tag.objects.all()]
    return success_response(tags)


@router.get('/articles/', response=dict)
def list_articles(
    request: HttpRequest,
    page: int = Query(1, ge=1, description='页码'),
    page_size: int = Query(10, ge=1, le=100, description='每页数量'),
    category_slug: str = Query('', description='按分类别名过滤'),
    tag_slug: str = Query('', description='按标签别名过滤'),
) -> dict:
    """文章列表（分页），可按 category_slug / tag_slug 过滤，仅返回已发布文章。"""
    qs = _published_articles()
    if category_slug:
        qs = qs.filter(category__slug=category_slug)
    if tag_slug:
        qs = qs.filter(tags__slug=tag_slug)
    total = qs.count()
    start = (page - 1) * page_size
    items = [article_to_out(request, article) for article in qs[start:start + page_size]]
    return success_response({'items': items, 'total': total, 'page': page, 'page_size': page_size})


@router.get('/articles/search/', response=dict)
def search_articles(
    request: HttpRequest,
    keyword: str = Query(..., description='关键词，标题模糊搜索'),
) -> dict:
    """按标题关键词搜索已发布文章，返回文章数组。"""
    qs = _published_articles().filter(title__icontains=keyword)
    return success_response([article_to_out(request, article) for article in qs])


@router.get('/articles/{slug}/', response=dict)
def article_detail(request: HttpRequest, slug: str) -> dict:
    """文章详情：阅读量 +1，仅返回已发布文章。"""
    try:
        article = (
            Article.objects.select_related('author', 'category')
            .prefetch_related('tags')
            .get(slug=slug, is_published=True)
        )
    except Article.DoesNotExist:
        raise HttpError(404, '文章不存在') from None
    Article.objects.filter(pk=article.pk).update(views=F('views') + 1)
    article.views += 1
    return success_response(article_to_detail(request, article).model_dump())


@admin_router.get('/articles/', response=dict, auth=jwt_auth)
def list_admin_articles(
    request: HttpRequest,
    page: int = Query(1, ge=1, description='页码'),
    page_size: int = Query(10, ge=1, le=100, description='每页数量'),
    is_published: bool | None = Query(None, description='按发布状态过滤'),
    keyword: str = Query('', description='标题关键词搜索'),
    category_slug: str = Query('', description='按分类别名过滤'),
) -> dict:
    """管理文章列表：返回全部文章（含未发布草稿），供后台管理与定位。"""
    qs = Article.objects.prefetch_related('tags', 'category')
    if is_published is not None:
        qs = qs.filter(is_published=is_published)
    if keyword:
        qs = qs.filter(title__icontains=keyword)
    if category_slug:
        qs = qs.filter(category__slug=category_slug)
    total = qs.count()
    start = (page - 1) * page_size
    items = [article_to_out(request, article) for article in qs[start:start + page_size]]
    return success_response({'items': items, 'total': total, 'page': page, 'page_size': page_size})


@admin_router.post('/articles/', response={201: dict}, auth=jwt_auth)
def create_article(
    request: HttpRequest,
    payload: ArticleCreateIn = Form(...),
    cover: UploadedFile = File(...),
    attachment: UploadedFile = File(...),
) -> Status:
    """创建文章（multipart，含封面与附件上传），返回 201。"""
    _validate_cover(cover)
    _validate_attachment(attachment)
    author = cast(User, request.auth)  # type: ignore[attr-defined]
    category, tag_ids = _resolve_category_and_tags(payload.category_id, payload.tag_ids)

    article = Article(
        title=payload.title,
        summary=payload.summary,
        publish_time=payload.publish_time,
        location=payload.location,
        author=author,
        category=category,
        cover_image_name=cover.name or '',
        file_name=attachment.name or '',
        is_published=payload.is_published,
    )
    article.cover_image.save(cover_upload_path(article, cover.name or ''), cover, save=False)
    article.file.save(file_upload_path(article, attachment.name or ''), attachment, save=False)

    base_slug = payload.slug or generate_slug(payload.title)
    slug_candidate = unique_slug(base_slug)
    attempts = 0
    while True:
        article.slug = slug_candidate
        try:
            article.save()
            break
        except IntegrityError:
            if not Article.objects.filter(slug=slug_candidate).exists():
                article.cover_image.delete(save=False)
                article.file.delete(save=False)
                raise HttpError(400, '创建失败：请检查分类/标签等参数是否正确') from None
            attempts += 1
            if attempts > 10:
                article.cover_image.delete(save=False)
                article.file.delete(save=False)
                raise HttpError(400, 'slug 冲突过多') from None
            slug_candidate = unique_slug(base_slug)
    if tag_ids:
        article.tags.set(tag_ids)
    return Status(201, success_response(article_to_out(request, article).model_dump(), code=201))


@admin_router.put('/articles/{article_id}/', response=dict, auth=jwt_auth)
def update_article(
    request: HttpRequest,
    article_id: int,
    payload: ArticleUpdateIn = Form(...),
    cover: UploadedFile = File(None),
    attachment: UploadedFile = File(None),
) -> dict:
    """更新文章（multipart，文件字段可选，不传则保留原文件）。"""
    article = Article.objects.filter(pk=article_id).first()
    if article is None:
        raise HttpError(404, '文章不存在')

    update_fields: dict[str, Any] = {}
    for field in ['title', 'summary', 'location', 'is_published']:
        value = getattr(payload, field)
        if value is not None:
            update_fields[field] = value
    if payload.slug is not None:
        update_fields['slug'] = unique_slug(payload.slug, exclude_id=article.pk)
    if payload.publish_time is not None:
        update_fields['publish_time'] = payload.publish_time
    if payload.category_id is not None:
        category = Category.objects.filter(pk=payload.category_id).first()
        if category is None:
            raise HttpError(400, '分类不存在')
        update_fields['category_id'] = category.pk
    if cover is not None:
        _validate_cover(cover)
        update_fields['cover_image'] = cover
        update_fields['cover_image_name'] = cover.name or ''
    if attachment is not None:
        _validate_attachment(attachment)
        update_fields['file'] = attachment
        update_fields['file_name'] = attachment.name or ''
    if payload.tag_ids is not None:
        valid_ids = set(Tag.objects.filter(pk__in=payload.tag_ids).values_list('id', flat=True))
        if len(valid_ids) != len(set(payload.tag_ids)):
            raise HttpError(400, '标签不存在')

    try:
        Article.objects.filter(pk=article.pk).update(**update_fields)
    except IntegrityError:
        if Article.objects.filter(slug=update_fields.get('slug', article.slug)).exists():
            raise HttpError(400, 'slug 已存在') from None
        raise HttpError(400, '更新失败：请检查分类/标签等参数是否正确') from None
    if payload.tag_ids is not None:
        article.tags.set(payload.tag_ids)

    article.refresh_from_db()
    return success_response(article_to_out(request, article).model_dump())


@admin_router.delete('/articles/{article_id}/', response=dict, auth=jwt_auth)
def delete_article(request: HttpRequest, article_id: int) -> dict:
    """按 id 删除文章（含草稿）。"""
    article = Article.objects.filter(pk=article_id).first()
    if article is None:
        raise HttpError(404, '文章不存在')
    article.delete()
    return success_response(message='删除成功')


@admin_router.delete('/articles/slug/{slug}/', response=dict, auth=jwt_auth)
def delete_article_by_slug(request: HttpRequest, slug: str) -> dict:
    """按 slug 删除文章（含草稿）。"""
    article = Article.objects.filter(slug=slug).first()
    if article is None:
        raise HttpError(404, '文章不存在')
    article.delete()
    return success_response(message='删除成功')


@admin_router.post('/categories/', response={201: dict}, auth=jwt_auth)
def create_category(request: HttpRequest, payload: CategoryIn) -> Status:
    """创建分类，slug 省略时由名称自动生成。"""
    category = Category.objects.create(
        name=payload.name,
        slug=unique_slug(payload.slug or generate_slug(payload.name), model=Category),
        description=payload.description,
    )
    data = CategoryOut(
        id=category.id, name=category.name, slug=category.slug, description=category.description
    ).model_dump()
    return Status(201, success_response(data, code=201))


@admin_router.get('/categories/{category_id}/', response=dict, auth=jwt_auth)
def get_category(request: HttpRequest, category_id: int) -> dict:
    """获取分类详情。"""
    category = Category.objects.filter(pk=category_id).first()
    if category is None:
        raise HttpError(404, '分类不存在')
    return success_response(
        CategoryOut(
            id=category.id, name=category.name, slug=category.slug, description=category.description
        ).model_dump()
    )


@admin_router.put('/categories/{category_id}/', response=dict, auth=jwt_auth)
def update_category(request: HttpRequest, category_id: int, payload: CategoryUpdateIn) -> dict:
    """更新分类，slug 省略时保留原值。"""
    category = Category.objects.filter(pk=category_id).first()
    if category is None:
        raise HttpError(404, '分类不存在')

    update_fields: dict[str, Any] = {}
    if payload.name is not None:
        update_fields['name'] = payload.name
    if payload.slug:
        update_fields['slug'] = unique_slug(payload.slug, model=Category, exclude_id=category.pk)
    if payload.description is not None:
        update_fields['description'] = payload.description

    try:
        Category.objects.filter(pk=category.pk).update(**update_fields)
    except IntegrityError:
        raise HttpError(400, 'slug 已存在') from None

    category.refresh_from_db()
    return success_response(
        CategoryOut(
            id=category.id, name=category.name, slug=category.slug, description=category.description
        ).model_dump()
    )


@admin_router.delete('/categories/{category_id}/', response=dict, auth=jwt_auth)
def delete_category(request: HttpRequest, category_id: int) -> dict:
    """删除分类：其下文章的 category 置空（SET_NULL），文章保留。"""
    category = Category.objects.filter(pk=category_id).first()
    if category is None:
        raise HttpError(404, '分类不存在')
    if category.slug == DEFAULT_CATEGORY_SLUG:
        raise HttpError(400, '默认分类不可删除')
    category.delete()
    return success_response(message='删除成功')


@admin_router.post('/tags/', response={201: dict}, auth=jwt_auth)
def create_tag(request: HttpRequest, payload: TagIn) -> Status:
    """创建标签，slug 省略时由名称自动生成。"""
    tag = Tag.objects.create(
        name=payload.name,
        slug=unique_slug(payload.slug or generate_slug(payload.name), model=Tag),
    )
    return Status(
        201,
        success_response(TagOut(id=tag.id, name=tag.name, slug=tag.slug).model_dump(), code=201),
    )


@admin_router.get('/tags/{tag_id}/', response=dict, auth=jwt_auth)
def get_tag(request: HttpRequest, tag_id: int) -> dict:
    """获取标签详情。"""
    tag = Tag.objects.filter(pk=tag_id).first()
    if tag is None:
        raise HttpError(404, '标签不存在')
    return success_response(TagOut(id=tag.id, name=tag.name, slug=tag.slug).model_dump())


@admin_router.put('/tags/{tag_id}/', response=dict, auth=jwt_auth)
def update_tag(request: HttpRequest, tag_id: int, payload: TagUpdateIn) -> dict:
    """更新标签，slug 省略时保留原值。"""
    tag = Tag.objects.filter(pk=tag_id).first()
    if tag is None:
        raise HttpError(404, '标签不存在')

    update_fields: dict[str, Any] = {}
    if payload.name is not None:
        update_fields['name'] = payload.name
    if payload.slug:
        update_fields['slug'] = unique_slug(payload.slug, model=Tag, exclude_id=tag.pk)

    try:
        Tag.objects.filter(pk=tag.pk).update(**update_fields)
    except IntegrityError:
        raise HttpError(400, 'slug 已存在') from None

    tag.refresh_from_db()
    return success_response(TagOut(id=tag.id, name=tag.name, slug=tag.slug).model_dump())


@admin_router.delete('/tags/{tag_id}/', response=dict, auth=jwt_auth)
def delete_tag(request: HttpRequest, tag_id: int) -> dict:
    """删除标签：仅解除与文章的关联（M2M），文章保留。"""
    tag = Tag.objects.filter(pk=tag_id).first()
    if tag is None:
        raise HttpError(404, '标签不存在')
    if tag.slug == DEFAULT_TAG_SLUG:
        raise HttpError(400, '默认标签不可删除')
    tag.delete()
    return success_response(message='删除成功')
