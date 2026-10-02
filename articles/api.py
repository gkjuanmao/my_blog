"""博客文章 API：公开文章浏览与管理接口。"""
import hashlib
import logging
import shutil
import uuid
from datetime import timedelta
from typing import Any, cast

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.db.models import F
from django.db.models.query import QuerySet
from django.http import FileResponse, HttpRequest
from django.utils import timezone
from ninja import File, Form, Query, Router, UploadedFile
from ninja.errors import HttpError
from ninja.responses import Status

from articles.archive import errors as archive_errors
from articles.archive import export as archive_export
from articles.archive import format as archive_format
from articles.archive import importer as archive_importer
from articles.archive import planner as archive_planner
from articles.archive import staging as archive_staging
from articles.archive import validate as archive_validate
from articles.archive.limits import ensure_free_space
from articles.archive.limits import limits as archive_limits
from articles.archive.locks import enforce_min_interval, import_lock
from common.responses import success_response
from common.schemas import ApiResponse, PageData
from users.authentication import JWTAuth, StaffJWTAuth
from users.models import User

from .convert import ConvertError, html_to_markdown
from .covers import CoverError, ProcessedCover
from .covers import process_cover as process_cover_image
from .defaults import DEFAULT_CATEGORY_SLUG, DEFAULT_TAG_SLUG, ensure_defaults
from .images import InlineImageError, process_inline_image, store_inline_image
from .models import ArchiveStaging, Article, Category, Tag, cover_upload_path, file_upload_path
from .rendering import render_markdown
from .schemas import (
    AdminArticleDetailOut,
    ArchiveImportCommitIn,
    ArchiveImportPlanIn,
    ArticleCreateIn,
    ArticleDetailOut,
    ArticleOut,
    ArticlePreviewIn,
    ArticleUpdateIn,
    BulkDeleteIn,
    CategoryIn,
    CategoryOut,
    CategoryUpdateIn,
    TagIn,
    TagOut,
    TagUpdateIn,
    article_to_admin_detail,
    article_to_detail,
    article_to_out,
)
from .utils import generate_slug, suggest_title_from_filename, unique_slug

router = Router(tags=['文章'])
admin_router = Router(tags=['文章管理'])

# 封面/附件的扩展名与体积上限统一从 settings 读取（见 config/settings/base.py），
# 避免与 articles/archive 两处维护；两者共用同一组白名单。

# 管理列表允许的排序字段（前缀 - 表示降序），用白名单避免用户传入任意字段
ADMIN_ARTICLE_ORDERING_FIELDS = {'publish_time', 'created_at', 'updated_at', 'views', 'title'}

# 单次批量删除的 id 上限
BULK_DELETE_MAX_IDS = 200

jwt_auth = JWTAuth()
staff_auth = StaffJWTAuth()

logger = logging.getLogger(__name__)


def _sha256_of(uploaded: UploadedFile) -> str:
    """计算上传文件的 SHA-256（源字节），供归档幂等键使用。

    读完必须 ``seek(0)``，否则后续 ``save()`` 会写入空文件。
    """
    digest = hashlib.sha256()
    for chunk in uploaded.chunks():
        digest.update(chunk)
    uploaded.seek(0)
    return digest.hexdigest()


def _extension(filename: str) -> str:
    """提取文件扩展名（小写，无扩展名返回空串）。"""
    return filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''


def _decode_html(raw: bytes) -> str:
    """解码 HTML 字节：优先 UTF-8，回落 GBK（部分国产手机便签导出为 GBK）。"""
    for encoding in ('utf-8', 'gbk'):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise HttpError(400, '无法识别文件编码，请使用 UTF-8 编码的 HTML')


def _validate_cover(cover: UploadedFile) -> None:
    """校验封面图片格式与大小。"""
    name = cover.name or ''
    if _extension(name) not in settings.COVER_EXTENSIONS:
        raise HttpError(400, '封面仅支持 JPG/PNG/WebP 格式')
    if (cover.size or 0) > settings.COVER_MAX_BYTES:
        raise HttpError(400, '封面大小不能超过 20MB')


def _process_cover(cover: UploadedFile) -> ProcessedCover:
    """校验并压缩上传的封面：统一转 WebP、限制最长边（与归档导入共用同一条管线）。

    落盘扩展名由返回值给出（恒为 ``webp``），调用方**不要**再用原始文件名后缀，
    否则会出现「.jpg 文件里装 WebP 字节」，nginx 会按扩展名发错 Content-Type。
    """
    raw = cover.read()
    # 与 _sha256_of 同理：别把上传流留在 EOF —— 同一个 UploadedFile 可能被复用
    # （测试里 fixture 常被循环使用），否则第二次会读到空字节而报"封面无法解析"。
    cover.seek(0)
    try:
        return process_cover_image(
            raw, _extension(cover.name or ''), max_pixels=settings.COVER_MAX_PIXELS
        )
    except CoverError as exc:
        raise HttpError(400, str(exc)) from None


def _validate_attachment(attachment: UploadedFile) -> None:
    """校验附件格式与大小。"""
    name = attachment.name or ''
    if _extension(name) not in settings.ATTACHMENT_EXTENSIONS:
        raise HttpError(400, '附件仅支持 PDF/Word 格式')
    if (attachment.size or 0) > settings.ATTACHMENT_MAX_BYTES:
        raise HttpError(400, '附件大小不能超过 50MB')


def _validate_content(content: str) -> None:
    """校验 Markdown 正文长度（ninja 的 Form 不会自动执行 max_length）。"""
    if len(content) > settings.ARTICLE_CONTENT_MAX_CHARS:
        raise HttpError(400, f'正文过长（上限 {settings.ARTICLE_CONTENT_MAX_CHARS} 字符）')


def _ensure_content_or_attachment(content: str | None, has_file: bool) -> None:
    """最终态校验：正文与附件至少填一项（create / update 共用）。"""
    if not (content or '').strip() and not has_file:
        raise HttpError(400, '正文与附件至少填写一项')


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


@router.get('/categories/', response=ApiResponse[list[CategoryOut]])
def list_categories(request: HttpRequest) -> dict:
    """获取所有分类。"""
    categories = [
        CategoryOut(id=c.id, name=c.name, slug=c.slug, description=c.description)
        for c in Category.objects.all()
    ]
    return success_response(categories)


@router.get('/tags/', response=ApiResponse[list[TagOut]])
def list_tags(request: HttpRequest) -> dict:
    """获取所有标签。"""
    tags = [TagOut(id=t.id, name=t.name, slug=t.slug) for t in Tag.objects.all()]
    return success_response(tags)


@router.get('/articles/', response=ApiResponse[PageData[ArticleOut]])
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


@router.get('/articles/search/', response=ApiResponse[PageData[ArticleOut]])
def search_articles(
    request: HttpRequest,
    keyword: str = Query(..., description='关键词，标题模糊搜索'),
    page: int = Query(1, ge=1, description='页码'),
    page_size: int = Query(10, ge=1, le=100, description='每页数量'),
) -> dict:
    """按标题关键词搜索已发布文章，分页返回（信封内 items/total/page/page_size）。"""
    qs = _published_articles().filter(title__icontains=keyword)
    total = qs.count()
    start = (page - 1) * page_size
    items = [article_to_out(request, article) for article in qs[start:start + page_size]]
    return success_response({'items': items, 'total': total, 'page': page, 'page_size': page_size})


@router.get('/articles/{slug}/', response=ApiResponse[ArticleDetailOut])
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


@admin_router.get('/articles/', response=ApiResponse[PageData[ArticleOut]], auth=jwt_auth)
def list_admin_articles(
    request: HttpRequest,
    page: int = Query(1, ge=1, description='页码'),
    page_size: int = Query(10, ge=1, le=100, description='每页数量'),
    is_published: bool | None = Query(None, description='按发布状态过滤'),
    keyword: str = Query('', description='标题关键词搜索'),
    category_slug: str = Query('', description='按分类别名过滤'),
    ordering: str = Query(
        '',
        description='排序字段：publish_time 升序 / -publish_time 降序；不传用默认排序',
    ),
) -> dict:
    """管理文章列表：返回全部文章（含未发布草稿），供后台管理与定位。"""
    qs = Article.objects.prefetch_related('tags', 'category')
    if is_published is not None:
        qs = qs.filter(is_published=is_published)
    if keyword:
        qs = qs.filter(title__icontains=keyword)
    if category_slug:
        qs = qs.filter(category__slug=category_slug)
    if ordering:
        field = ordering.lstrip('-')
        if field not in ADMIN_ARTICLE_ORDERING_FIELDS:
            raise HttpError(400, '不支持的排序字段')
        # 追加 -id 作次要排序键，避免排序值相同时翻页出现重复/遗漏
        qs = qs.order_by(ordering, '-id')
    total = qs.count()
    start = (page - 1) * page_size
    items = [article_to_out(request, article) for article in qs[start:start + page_size]]
    return success_response({'items': items, 'total': total, 'page': page, 'page_size': page_size})


@admin_router.get('/articles/export/', response=ApiResponse[dict], auth=staff_auth)
def create_export(
    request: HttpRequest,
    ids: str = Query('', description='逗号分隔的文章 id；与筛选参数互斥，以 ids 为准'),
    keyword: str = Query('', description='标题关键词（与列表接口同义）'),
    category_slug: str = Query('', description='按分类别名过滤'),
    is_published: bool | None = Query(None, description='按发布状态过滤'),
) -> dict:
    """创建导出票据（**不**直接回 zip）。

    ⚠️ 本路由与 /articles/export/estimate/ **必须注册在 /articles/{article_id}/ 之前**：
    后者没有 int 转换器，`resolve()` 实测会把它解析成 article_id='export'。
    """
    lim = archive_limits()
    id_list = _parse_ids(ids)
    if len(id_list) > lim.max_ids_per_request:
        raise HttpError(400, f'ids 数量超过上限 {lim.max_ids_per_request}，请改用筛选导出')

    articles = archive_export.select_articles(
        ids=id_list,
        keyword=keyword,
        category_slug=category_slug,
        is_published=is_published,
    )
    if not articles:
        raise HttpError(400, '没有符合条件的文章')

    out_path = None
    try:
        estimate = archive_export.estimate_export(articles, lim=lim)
        ensure_free_space(needed_bytes=estimate.source_bytes, extra_dirs=(lim.root,))
        archive_staging.ensure_subdirs()
        out_path = (
            archive_staging.archive_root()
            / archive_staging.EXPORTS_DIR
            / f'{uuid.uuid4().hex}.zip'
        )
        info = archive_export.build_archive(articles, out_path, lim=lim)
    except archive_errors.ArchiveError as exc:
        if out_path is not None:
            out_path.unlink(missing_ok=True)
        raise _archive_error(exc) from None

    ticket = archive_staging.create_ticket(
        user=cast(User, request.auth),  # type: ignore[attr-defined]
        kind='export',
        path=out_path,
        filename=archive_export.export_filename(),
        size=info['bytes'],
    )
    return success_response({
        'ticket': str(ticket.id),
        'download_url': f'/api/v1/admin/archives/{ticket.id}/',
        'expires_at': ticket.expires_at.isoformat(),
        'filename': ticket.filename,
        'count': info['count'],
        'bytes': info['bytes'],
        'warnings': info['warnings'],
    })


@admin_router.get('/articles/export/estimate/', response=ApiResponse[dict], auth=staff_auth)
def estimate_export(
    request: HttpRequest,
    ids: str = Query(''),
    keyword: str = Query(''),
    category_slug: str = Query(''),
    is_published: bool | None = Query(None),
) -> dict:
    """导出预估：篇数 / 源字节 / 条目数 / **是否可回导**。"""
    lim = archive_limits()
    id_list = _parse_ids(ids)
    if len(id_list) > lim.max_ids_per_request:
        raise HttpError(400, f'ids 数量超过上限 {lim.max_ids_per_request}')
    articles = archive_export.select_articles(
        ids=id_list,
        keyword=keyword,
        category_slug=category_slug,
        is_published=is_published,
    )
    estimate = archive_export.estimate_export(articles, lim=lim)
    return success_response(estimate.to_dict())


@admin_router.post('/articles/bulk-delete/', response=ApiResponse[dict], auth=jwt_auth)
def bulk_delete_articles(request: HttpRequest, payload: BulkDeleteIn) -> dict:
    """批量删除文章（含草稿）。

    - 一次请求代替 N 次单删，避免前端串行请求与中途部分成功无法交代；
    - 封面/附件文件仍由 ``articles/signals.py`` 的 ``post_delete`` 统一清理
      （``QuerySet.delete()`` 同样会逐条发出该信号）；
    - 幂等友好：已不存在的 id 不算错误，单独在 ``not_found`` 里回显。

    ⚠️ 本路由必须注册在 ``/articles/{article_id}/`` 之前（同 export：详情路由
    没有 int 转换器，会先把路径吃掉，POST 到这里会变成 405）。
    """
    ids = payload.ids
    if not ids:
        raise HttpError(400, 'ids 不能为空')
    if len(ids) > BULK_DELETE_MAX_IDS:
        raise HttpError(400, f'单次最多删除 {BULK_DELETE_MAX_IDS} 篇')

    unique_ids = sorted({int(value) for value in ids})
    existing = list(
        Article.objects.filter(pk__in=unique_ids).values_list('id', flat=True)
    )
    missing = [value for value in unique_ids if value not in set(existing)]
    if existing:
        with transaction.atomic():
            Article.objects.filter(pk__in=existing).delete()

    return success_response({
        'requested': len(unique_ids),
        'deleted': len(existing),
        'not_found': missing,
    })


@admin_router.post('/articles/preview/', response=ApiResponse[dict], auth=jwt_auth)
def preview_article_content(request: HttpRequest, payload: ArticlePreviewIn) -> dict:
    """预览 Markdown 正文（只渲染消毒，不落库）。

    ⚠️ 本路由必须注册在 ``/articles/{article_id}/`` 之前：详情路由没有 int 转换器，
    会把 ``preview`` 解析成 ``article_id``（同 export / bulk-delete）。
    """
    content = payload.content or ''
    _validate_content(content)
    return success_response({'content_html': render_markdown(content)})


@admin_router.post('/articles/images/', response=ApiResponse[dict], auth=staff_auth)
def upload_inline_image(request: HttpRequest, image: UploadedFile = File(...)) -> dict:
    """上传正文内联图片：服务端压缩为 WebP、按内容寻址落盘，返回可插入正文的 URL。

    ⚠️ 与 preview 同理，本路由必须注册在 ``/articles/{article_id}/`` 之前。
    """
    ext = _extension(image.name or '')
    if ext not in settings.INLINE_IMAGE_EXTENSIONS:
        raise HttpError(400, '图片仅支持 JPG/PNG/WebP 格式')
    raw = image.read()
    try:
        processed = process_inline_image(raw, ext)
    except InlineImageError as exc:
        raise HttpError(400, str(exc)) from None
    rel = store_inline_image(processed.data)
    return success_response({
        'url': f'{settings.MEDIA_URL}{rel}',
        'width': processed.width,
        'height': processed.height,
        'bytes': len(processed.data),
        'original_bytes': len(raw),
    })


@admin_router.post('/articles/convert-html/', response=ApiResponse[dict], auth=staff_auth)
def convert_html_article(
    request: HttpRequest,
    file: UploadedFile = File(None),
    html: str = Form(''),
) -> dict:
    """把手机/第三方导出的 HTML 转成 Markdown（**不落库**），供后台「导入 HTML」回填编辑器。

    输入二选一：``file``（走 multipart 文件通道，上限 ``HTML_IMPORT_MAX_BYTES``）或
    ``html``（粘贴文本）。正文里的 base64 内嵌图会压成 WebP 落盘并改写为
    ``/media/inline/...``；外链图与不可读来源分别保留 / 移除并告警。

    ⚠️ 与 preview / images 同理，本路由必须注册在 ``/articles/{article_id}/`` 之前。
    """
    limit = int(settings.HTML_IMPORT_MAX_BYTES)
    limit_mb = limit // 1024**2
    if file is not None:
        if (file.size or 0) > limit:
            raise HttpError(400, f'HTML 文件不能超过 {limit_mb}MB')
        raw = file.read()
    else:
        raw = html.encode('utf-8')

    if not raw.strip():
        raise HttpError(400, '请选择 HTML 文件或粘贴 HTML 内容')
    if len(raw) > limit:
        raise HttpError(400, f'HTML 文件不能超过 {limit_mb}MB')

    try:
        result = html_to_markdown(_decode_html(raw))
    except ConvertError as exc:
        raise HttpError(400, str(exc)) from None

    return success_response({
        'markdown': result.markdown,
        'images': result.images,
        'warnings': result.warnings,
        # 便签导出的正文里通常没有标题，标题只在文件名里（如「44 上海-罗马_202610030035.html」）
        'suggested_title': suggest_title_from_filename(file.name or '') if file else '',
    })


@admin_router.get(
    '/articles/{article_id}/', response=ApiResponse[AdminArticleDetailOut], auth=jwt_auth
)
def get_admin_article(request: HttpRequest, article_id: int) -> dict:
    """获取单篇文章详情（含草稿与原始 Markdown），供后台编辑回填。"""
    article = (
        Article.objects.select_related('author', 'category')
        .prefetch_related('tags')
        .filter(pk=article_id)
        .first()
    )
    if article is None:
        raise HttpError(404, '文章不存在')
    return success_response(article_to_admin_detail(request, article).model_dump())


@admin_router.post('/articles/', response={201: ApiResponse[ArticleOut]}, auth=jwt_auth)
def create_article(
    request: HttpRequest,
    payload: ArticleCreateIn = Form(...),
    cover: UploadedFile = File(...),
    attachment: UploadedFile = File(None),
) -> Status:
    """创建文章（multipart，封面必填、附件可选，正文为主），返回 201。"""
    _validate_cover(cover)
    processed_cover = _process_cover(cover)
    content = payload.content or ''
    _validate_content(content)
    if attachment is not None:
        _validate_attachment(attachment)
    _ensure_content_or_attachment(content, attachment is not None)
    author = cast(User, request.auth)  # type: ignore[attr-defined]
    category, tag_ids = _resolve_category_and_tags(payload.category_id, payload.tag_ids)

    article = Article(
        title=payload.title,
        summary=payload.summary,
        content=content,
        publish_time=payload.publish_time,
        location=payload.location,
        author=author,
        category=category,
        cover_image_name=cover.name or '',
        cover_image_sha256=processed_cover.sha256,
        file_name=(attachment.name or '') if attachment is not None else '',
        file_sha256=_sha256_of(attachment) if attachment is not None else '',
        is_published=payload.is_published,
    )
    article.cover_image.save(
        cover_upload_path(article, f'cover.{processed_cover.ext}'),
        ContentFile(processed_cover.data),
        save=False,
    )
    if attachment is not None:
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


def _delete_stored_files(names: list[str | None]) -> None:
    """删除 storage 中的文件，忽略空值与已不存在的文件。"""
    for name in names:
        if name:
            default_storage.delete(name)


@admin_router.put('/articles/{article_id}/', response=ApiResponse[ArticleOut], auth=jwt_auth)
def update_article(
    request: HttpRequest,
    article_id: int,
    payload: ArticleUpdateIn = Form(...),
    cover: UploadedFile = File(None),
    attachment: UploadedFile = File(None),
) -> dict:
    """更新文章（multipart，文件字段可选，不传则保留原文件）。

    走 Model.save(update_fields=...) 而非 QuerySet.update()：后者绕过
    FileField.pre_save()，上传的文件不会写入 storage，字段还会被存成客户端原始
    文件名（cover_image='photo.jpg'），导致 cover_image_url 指向不存在的文件；
    auto_now 的 updated_at 也不会刷新。update_fields 同时避免覆盖 views 等
    未提交字段。被替换掉的旧文件在保存成功后清理。
    """
    article = Article.objects.filter(pk=article_id).first()
    if article is None:
        raise HttpError(404, '文章不存在')

    # 先校验后落盘：校验失败不得改动数据，也不留下新写入的文件
    # （封面顺带在这压缩；下面再用 `is not None` 收窄类型，别改成依赖同一条件）
    processed_cover: ProcessedCover | None = None
    if cover is not None:
        _validate_cover(cover)
        processed_cover = _process_cover(cover)
    if attachment is not None:
        _validate_attachment(attachment)
    if payload.content is not None:
        _validate_content(payload.content)

    update_fields: set[str] = set()
    for field in ['title', 'summary', 'content', 'location', 'is_published']:
        value = getattr(payload, field)
        if value is not None:
            setattr(article, field, value)
            update_fields.add(field)
    if payload.slug is not None:
        article.slug = unique_slug(payload.slug, exclude_id=article.pk)
        update_fields.add('slug')
    if payload.publish_time is not None:
        article.publish_time = payload.publish_time
        update_fields.add('publish_time')
    if payload.category_id is not None:
        category = Category.objects.filter(pk=payload.category_id).first()
        if category is None:
            raise HttpError(400, '分类不存在')
        article.category = category
        update_fields.add('category')

    tag_ids: list[int] | None = None
    if payload.tag_ids is not None:
        valid_ids = set(Tag.objects.filter(pk__in=payload.tag_ids).values_list('id', flat=True))
        if len(valid_ids) != len(set(payload.tag_ids)):
            raise HttpError(400, '标签不存在')
        tag_ids = payload.tag_ids

    # 最终态校验：仅当本次请求涉及正文或附件时才判，避免"只改 slug/标题"被误判；
    # 判的是「更新后」的状态，防止清空正文又不传附件而产出空文章。
    if payload.content is not None or attachment is not None:
        content_after = payload.content if payload.content is not None else article.content
        _ensure_content_or_attachment(
            content_after, attachment is not None or bool(article.file)
        )

    stale_names: list[str | None] = []
    new_names: list[str | None] = []
    if cover is not None and processed_cover is not None:
        stale_names.append(article.cover_image.name)
        article.cover_image.save(
            cover_upload_path(article, f'cover.{processed_cover.ext}'),
            ContentFile(processed_cover.data),
            save=False,
        )
        article.cover_image_name = cover.name or ''
        article.cover_image_sha256 = processed_cover.sha256
        new_names.append(article.cover_image.name)
        update_fields.update({'cover_image', 'cover_image_name', 'cover_image_sha256'})
    if attachment is not None:
        stale_names.append(article.file.name)
        article.file.save(file_upload_path(article, attachment.name or ''), attachment, save=False)
        article.file_name = attachment.name or ''
        article.file_sha256 = _sha256_of(attachment)
        new_names.append(article.file.name)
        update_fields.update({'file', 'file_name', 'file_sha256'})

    if not update_fields and tag_ids is None:
        return success_response(article_to_out(request, article).model_dump())

    update_fields.add('updated_at')
    try:
        article.save(update_fields=update_fields)
    except IntegrityError:
        # 数据库未写入，回收刚落盘的新文件，旧文件保持不动
        _delete_stored_files(new_names)
        conflict = (
            'slug' in update_fields
            and Article.objects.filter(slug=article.slug).exclude(pk=article.pk).exists()
        )
        if conflict:
            raise HttpError(400, 'slug 已存在') from None
        raise HttpError(400, '更新失败：请检查分类/标签等参数是否正确') from None

    if tag_ids is not None:
        article.tags.set(tag_ids)
    _delete_stored_files(stale_names)

    article.refresh_from_db()
    return success_response(article_to_out(request, article).model_dump())


@admin_router.delete('/articles/{article_id}/', response=ApiResponse[None], auth=jwt_auth)
def delete_article(request: HttpRequest, article_id: int) -> dict:
    """按 id 删除文章（含草稿）。"""
    article = Article.objects.filter(pk=article_id).first()
    if article is None:
        raise HttpError(404, '文章不存在')
    article.delete()
    return success_response(message='删除成功')


@admin_router.delete('/articles/slug/{slug}/', response=ApiResponse[None], auth=jwt_auth)
def delete_article_by_slug(request: HttpRequest, slug: str) -> dict:
    """按 slug 删除文章（含草稿）。"""
    article = Article.objects.filter(slug=slug).first()
    if article is None:
        raise HttpError(404, '文章不存在')
    article.delete()
    return success_response(message='删除成功')


@admin_router.post('/categories/', response={201: ApiResponse[CategoryOut]}, auth=jwt_auth)
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


@admin_router.get('/categories/{category_id}/', response=ApiResponse[CategoryOut], auth=jwt_auth)
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


@admin_router.put('/categories/{category_id}/', response=ApiResponse[CategoryOut], auth=jwt_auth)
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


@admin_router.delete('/categories/{category_id}/', response=ApiResponse[None], auth=jwt_auth)
def delete_category(request: HttpRequest, category_id: int) -> dict:
    """删除分类：其下文章的 category 置空（SET_NULL），文章保留。"""
    category = Category.objects.filter(pk=category_id).first()
    if category is None:
        raise HttpError(404, '分类不存在')
    if category.slug == DEFAULT_CATEGORY_SLUG:
        raise HttpError(400, '默认分类不可删除')
    category.delete()
    return success_response(message='删除成功')


@admin_router.post('/tags/', response={201: ApiResponse[TagOut]}, auth=jwt_auth)
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


@admin_router.get('/tags/{tag_id}/', response=ApiResponse[TagOut], auth=jwt_auth)
def get_tag(request: HttpRequest, tag_id: int) -> dict:
    """获取标签详情。"""
    tag = Tag.objects.filter(pk=tag_id).first()
    if tag is None:
        raise HttpError(404, '标签不存在')
    return success_response(TagOut(id=tag.id, name=tag.name, slug=tag.slug).model_dump())


@admin_router.put('/tags/{tag_id}/', response=ApiResponse[TagOut], auth=jwt_auth)
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


@admin_router.delete('/tags/{tag_id}/', response=ApiResponse[None], auth=jwt_auth)
def delete_tag(request: HttpRequest, tag_id: int) -> dict:
    """删除标签：仅解除与文章的关联（M2M），文章保留。"""
    tag = Tag.objects.filter(pk=tag_id).first()
    if tag is None:
        raise HttpError(404, '标签不存在')
    if tag.slug == DEFAULT_TAG_SLUG:
        raise HttpError(400, '默认标签不可删除')
    tag.delete()
    return success_response(message='删除成功')


# ---------------------------------------------------------------------------
# 文章归档：票据下载 + 两阶段导入
# 路由顺序敏感：/articles/export/ 必须早于 /articles/{article_id}/（见上方注释）。
# ---------------------------------------------------------------------------


def _archive_error(exc: archive_errors.ArchiveError) -> HttpError:
    """把归档异常映射成统一信封的 HttpError（400/409/410/429/503）。"""
    return HttpError(exc.http_status, exc.message)


def _parse_ids(raw: str) -> list[int]:
    """解析逗号分隔的文章 id 列表。"""
    out: list[int] = []
    for part in (raw or '').split(','):
        text = part.strip()
        if not text:
            continue
        if not text.isdigit():
            raise HttpError(400, 'ids 必须是逗号分隔的正整数')
        out.append(int(text))
    return out


def _package_info_dict(info: archive_validate.PackageInfo) -> dict:
    """报告里的包级信息（不透传原始异常文本）。"""
    return {
        'entries': info.entries_count,
        'bytes_uncompressed': info.uncompressed_bytes,
        'sha256': info.sha256,
    }


def _plan_report(plan: archive_planner.Plan, *, dry_run: bool, package: dict) -> dict:
    """预检/执行统一的报告结构（同一 planner 产出）。"""
    return {
        'dry_run': dry_run,
        'schema': archive_format.REPORT_SCHEMA,
        'package': package,
        'totals': plan.totals(),
        'items': [item.to_dict() for item in plan.items],
    }


@admin_router.get('/archives/{ticket}/', auth=None)
def download_archive(request: HttpRequest, ticket: str):
    """一次性票据下载（能力 URL：auth=None，凭票据本身授权）。

    票据在**流开始前**原子占用；第二次访问一律 410，可用 reissue 重签。
    """
    if not archive_staging.is_uuid(ticket):
        raise HttpError(404, '归档票据不存在')
    record = archive_staging.claim_ticket(ticket)
    if record is None:
        raise HttpError(410, '票据已使用或已过期，请重新生成')
    try:
        path = archive_staging.ticket_file(record)
    except archive_errors.ArchiveError as exc:
        raise _archive_error(exc) from None
    return FileResponse(open(path, 'rb'), as_attachment=True, filename=record.filename)


@admin_router.post('/archives/{ticket}/reissue/', response=ApiResponse[dict], auth=staff_auth)
def reissue_archive(request: HttpRequest, ticket: str) -> dict:
    """重签票据（下载中断或过期后用）。"""
    if not archive_staging.is_uuid(ticket):
        raise HttpError(404, '归档票据不存在')
    from .models import ArchiveTicket

    record = ArchiveTicket.objects.filter(pk=ticket).first()
    if record is None:
        raise HttpError(404, '归档票据不存在')
    record = archive_staging.reissue_ticket(record)
    return success_response({
        'ticket': str(record.id),
        'download_url': f'/api/v1/admin/archives/{record.id}/',
        'expires_at': record.expires_at.isoformat(),
        'filename': record.filename,
    })


@admin_router.post('/articles/import/stage/', response=ApiResponse[dict], auth=staff_auth)
def stage_import(
    request: HttpRequest,
    file: UploadedFile = File(...),
    strategy: str = Form('skip'),
) -> dict:
    """第一阶段：上传并完整校验压缩包，返回 staged_id + 预检报告（不写任何业务数据）。"""
    lim = archive_limits()
    size = file.size or 0
    if size > lim.max_upload_bytes:
        raise HttpError(413, f'压缩包超过上限 {lim.max_upload_bytes} 字节')
    if strategy not in archive_planner.STRATEGIES:
        raise HttpError(400, 'strategy 取值非法')

    staging_id = uuid.uuid4()
    staging_dir = None
    try:
        archive_staging.ensure_subdirs()
        ensure_free_space(needed_bytes=size, extra_dirs=(lim.root,))
        staging_dir = archive_staging.create_staging_dir(staging_id)
        package_path = staging_dir / 'package.zip'
        with open(package_path, 'wb') as handle:
            for chunk in file.chunks():
                handle.write(chunk)
        info = archive_validate.validate_package(package_path, limits_override=lim)
        plan = archive_planner.build_plan(
            info.entries,
            strategy=strategy,
            user=cast(User, request.auth),  # type: ignore[attr-defined]
            lim=lim,
        )
    except archive_errors.ArchiveError as exc:
        if staging_dir is not None:
            shutil.rmtree(staging_dir, ignore_errors=True)
        raise _archive_error(exc) from None
    except Exception:
        if staging_dir is not None:
            shutil.rmtree(staging_dir, ignore_errors=True)
        logger.exception('归档预检失败')
        raise HttpError(400, '压缩包处理失败') from None

    staging = ArchiveStaging.objects.create(
        id=staging_id,
        user=cast(User, request.auth),  # type: ignore[attr-defined]
        dir=archive_staging.rel_path(staging_dir),
        sha256=info.sha256,
        bytes=size,
        entries=info.entries_count,
        expires_at=timezone.now() + timedelta(seconds=lim.staging_ttl),
    )
    report = _plan_report(plan, dry_run=True, package=_package_info_dict(info))
    report['staged_id'] = str(staging.id)
    return success_response(report)


@admin_router.post('/articles/import/plan/', response=ApiResponse[dict], auth=staff_auth)
def plan_import(request: HttpRequest, payload: ArchiveImportPlanIn) -> dict:
    """按指定策略对已暂存的包重新预检（**不重传文件**）。

    前端在用户修改策略时需要准确报告，否则只能重传整个包（对大包代价不可接受）。
    """
    lim = archive_limits()
    if payload.strategy not in archive_planner.STRATEGIES:
        raise HttpError(400, 'strategy 取值非法')
    if not archive_staging.is_uuid(payload.staged_id):
        raise HttpError(404, '暂存包不存在')
    user = cast(User, request.auth)  # type: ignore[attr-defined]
    staging = ArchiveStaging.objects.filter(pk=payload.staged_id, user=user).first()
    if staging is None:
        raise HttpError(404, '暂存包不存在')
    if staging.consumed_at is not None:
        raise HttpError(409, '该暂存包已被执行，请重新上传')
    if staging.expires_at <= timezone.now():
        raise HttpError(409, '该暂存包已过期，请重新上传')

    try:
        package_path = archive_staging.staging_archive_path(staging)
        info = archive_validate.validate_package(package_path, limits_override=lim)
        plan = archive_planner.build_plan(
            info.entries, strategy=payload.strategy, user=user, lim=lim
        )
    except archive_errors.ArchiveError as exc:
        raise _archive_error(exc) from None

    report = _plan_report(plan, dry_run=True, package=_package_info_dict(info))
    report['staged_id'] = str(staging.id)
    return success_response(report)


@admin_router.post('/articles/import/commit/', response=ApiResponse[dict], auth=staff_auth)
def commit_import(request: HttpRequest, payload: ArchiveImportCommitIn) -> dict:
    """第二阶段：凭 staged_id 执行（**重新解析原包**，保证与预检一致）。"""
    from .models import ArchiveTicket

    lim = archive_limits()
    if payload.strategy not in archive_planner.STRATEGIES:
        raise HttpError(400, 'strategy 取值非法')
    if not archive_staging.is_uuid(payload.staged_id):
        raise HttpError(404, '暂存包不存在')
    user = cast(User, request.auth)  # type: ignore[attr-defined]
    staging = ArchiveStaging.objects.filter(pk=payload.staged_id, user=user).first()
    if staging is None:
        raise HttpError(404, '暂存包不存在')

    now = timezone.now()
    try:
        # 顺序很重要：先取锁与限流，**最后**才消费 staged_id。
        # 否则被 429/409 挡掉时暂存包已被标记消费，用户得白传一次（含 1GB 包）。
        with import_lock(lim):
            enforce_min_interval(user.id, lim)
            claimed = ArchiveStaging.objects.filter(
                pk=staging.pk, consumed_at__isnull=True, expires_at__gt=now
            ).update(consumed_at=now, lease_until=now + timedelta(seconds=600))
            if claimed != 1:
                raise HttpError(409, '该暂存包已被执行或已过期，请重新上传')

            package_path = archive_staging.staging_archive_path(staging)
            info = archive_validate.validate_package(package_path, limits_override=lim)
            plan = archive_planner.build_plan(
                info.entries, strategy=payload.strategy, user=user, lim=lim
            )

            rollback = None
            if plan.has_overwrite:
                affected = list(
                    Article.objects.filter(pk__in=plan.touched_ids)
                    .select_related('author', 'category')
                    .prefetch_related('tags')
                )
                if affected:
                    archive_staging.ensure_subdirs()
                    out_path = (
                        archive_staging.archive_root()
                        / archive_staging.ROLLBACKS_DIR
                        / f'{uuid.uuid4().hex}.zip'
                    )
                    archive_export.build_rollback_archive(affected, out_path, lim=lim)
                    ticket = archive_staging.create_ticket(
                        user=user,
                        kind=ArchiveTicket.Kind.ROLLBACK,
                        path=out_path,
                        filename=f'rollback-{archive_export.export_filename()}',
                        size=out_path.stat().st_size,
                    )
                    rollback = {
                        'count': len(affected),
                        'ticket': str(ticket.id),
                        'download_url': f'/api/v1/admin/archives/{ticket.id}/',
                        'expires_at': ticket.expires_at.isoformat(),
                    }

            options = archive_importer.ImportOptions(
                strategy=payload.strategy,
                auto_create_taxonomy=payload.auto_create_taxonomy,
                as_draft=payload.as_draft,
                user=user,
            )
            report = archive_importer.execute_plan(
                plan,
                options=options,
                package=_package_info_dict(info),
                package_path=package_path,
            )
            data = report.to_dict(
                dry_run=False, plan=plan, package=_package_info_dict(info)
            )
            data['rollback_package'] = rollback
    except archive_errors.ArchiveError as exc:
        raise _archive_error(exc) from None
    finally:
        ArchiveStaging.objects.filter(pk=staging.pk).update(lease_until=None)

    return success_response(data)


@admin_router.delete(
    '/articles/import/stage/{staging_id}/', response=ApiResponse[None], auth=staff_auth
)
def discard_staging(request: HttpRequest, staging_id: str) -> dict:
    """放弃一个暂存包。"""
    if not archive_staging.is_uuid(staging_id):
        raise HttpError(404, '暂存包不存在')
    user = cast(User, request.auth)  # type: ignore[attr-defined]
    staging = ArchiveStaging.objects.filter(pk=staging_id, user=user).first()
    if staging is None:
        raise HttpError(404, '暂存包不存在')
    shutil.rmtree(archive_staging.staging_path(staging.dir), ignore_errors=True)
    staging.delete()
    return success_response(message='已丢弃')


@admin_router.get('/articles/import/limits/', response=ApiResponse[dict], auth=staff_auth)
def archive_limits_view(request: HttpRequest) -> dict:
    """把归档上限暴露给前端，便于上传前本地预检（避免白传 1GB）。"""
    lim = archive_limits()
    return success_response({
        'max_upload_bytes': lim.max_upload_bytes,
        'max_entries': lim.max_entries,
        'max_total_uncompressed': lim.max_total_uncompressed,
        'max_member_bytes': lim.max_member_bytes,
        'max_articles_per_export': lim.max_articles_per_export,
        'max_ids_per_request': lim.max_ids_per_request,
        'cover_extensions': sorted(settings.COVER_EXTENSIONS),
        'attachment_extensions': sorted(settings.ATTACHMENT_EXTENSIONS),
        'attachment_legacy_extensions': sorted(settings.ATTACHMENT_LEGACY_EXTENSIONS),
        'cover_max_bytes': settings.COVER_MAX_BYTES,
        'attachment_max_bytes': settings.ATTACHMENT_MAX_BYTES,
    })
