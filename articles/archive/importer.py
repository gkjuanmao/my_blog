"""执行计划：写库、落盘媒体、失败补偿。

关键不变量：
- 每篇一个 ``transaction.atomic()``（分类/标签的自动创建也在同一保存点内，失败一起回滚）。
- 媒体落盘**不在事务内**，因此显式记录本次写入的文件名，异常时逐个回收。
  **内联图不参与补偿**：它是内容寻址、可重物化，且同一张图可能被多篇文章共用，
  回滚时删除会误伤别的文章（孤儿统一交给 ``purge_inline_images``）。
- update 一律 ``save(update_fields=...)``，且**永不读写** views/created_at/updated_at/author。
- ``as_draft`` 只作用于 create（决策 D22），对 update 忽略并告警。
- 校验阶段**不驻留媒体字节**（避免 1GiB 上限下整站 OOM），因此这里按需重开暂存 zip
  读取原始字节，并**重跑** ``process_cover`` / ``process_inline_image``，
  用**产物**哈希与校验阶段记录的 ``stored_sha256`` 比对。
"""
import logging
import os
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction

from articles.images import (
    InlineImageError,
    process_inline_image,
    store_inline_image,
)
from articles.models import Article, Category, Tag, cover_upload_path, file_upload_path
from articles.utils import unique_slug

from .errors import ItemError
from .format import COVER_BASENAME, REPORT_SCHEMA, sha256_bytes
from .limits import Limits
from .planner import Plan, PlanItem
from .validate import normalize_entry_name, process_cover

logger = logging.getLogger(__name__)

_CTRL_RE = re.compile(r'[\x00-\x1f\x7f]')


@dataclass
class ImportOptions:
    """一次导入的选项。"""

    strategy: str = 'skip'
    auto_create_taxonomy: bool = True
    as_draft: bool = False
    user: Any = None


@dataclass
class ImportReport:
    """导入结果。"""

    items: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self, *, dry_run: bool, plan: Plan, package: dict) -> dict:
        return {
            'dry_run': dry_run,
            'schema': REPORT_SCHEMA,
            'package': package,
            'totals': plan.totals(),
            'items': self.items,
        }


def sanitize_original_name(name: str, fallback: str) -> str:
    """净化展示用原始文件名：去路径分隔符与控制字符，截断到 255。"""
    cleaned = _CTRL_RE.sub('', str(name or ''))
    cleaned = cleaned.replace('/', '_').replace('\\', '_').strip()
    return (cleaned or fallback)[:255]


def _delete_files(names: list[str]) -> None:
    """回收本次新落盘的文件（忽略空值与已不存在者）。"""
    for name in names:
        if name:
            try:
                default_storage.delete(name)
            except OSError:  # pragma: no cover
                logger.warning('回收归档文件失败: %s', name, exc_info=True)


def _resolve_category(parsed, options: ImportOptions, warnings: list[str]):
    """按 slug 解析分类；不存在且允许时创建（绝不修改已存在的名称/描述）。"""
    if parsed.category is None:
        return None, False
    cat_slug = str(parsed.category['slug'])
    existing = Category.objects.filter(slug=cat_slug).first()
    if existing is not None:
        if parsed.category.get('name') and parsed.category['name'] != existing.name:
            warnings.append(f'分类 {cat_slug} 已存在且名称不同，沿用既有名称「{existing.name}」')
        return existing, False
    if not options.auto_create_taxonomy:
        warnings.append(f'分类 {cat_slug} 不存在且未开启自动创建，该篇分类留空')
        return None, False
    name = str(parsed.category.get('name') or cat_slug)[:100]
    category = Category.objects.create(
        slug=cat_slug,
        name=name,
        description=str(parsed.category.get('description') or '')[:255],
    )
    return category, True


def _resolve_tags(parsed, options: ImportOptions, warnings: list[str]) -> tuple[list, int]:
    """按 slug 解析标签，返回（标签对象列表, 新建数量）。"""
    if parsed.tags is None:
        return [], 0
    resolved = []
    created = 0
    for item in parsed.tags:
        tag_slug = str(item['slug'])
        tag = Tag.objects.filter(slug=tag_slug).first()
        if tag is None:
            if not options.auto_create_taxonomy:
                warnings.append(f'标签 {tag_slug} 不存在且未开启自动创建，已跳过')
                continue
            tag = Tag.objects.create(
                slug=tag_slug, name=str(item.get('name') or tag_slug)[:100]
            )
            created += 1
        elif item.get('name') and item['name'] != tag.name:
            warnings.append(f'标签 {tag_slug} 已存在且名称不同，沿用既有名称「{tag.name}」')
        resolved.append(tag)
    return resolved, created


def _read_member(zf: zipfile.ZipFile, name: str, limit: int) -> bytes:
    """从暂存包按需读取一个条目的原始字节（校验阶段没有驻留它们）。"""
    target = normalize_entry_name(name)
    info = next(
        (i for i in zf.infolist() if normalize_entry_name(i.filename) == target), None
    )
    if info is None:
        raise ItemError(f'包内缺少条目: {target}')
    if info.file_size and info.file_size > limit:
        raise ItemError(f'条目超过上限: {target}')
    with zf.open(info) as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ItemError(f'条目超过上限: {target}')
    return data


def _inline_url(name: str) -> str:
    """内联图文件名 → 公开 URL。"""
    return f'{settings.MEDIA_URL}{settings.INLINE_IMAGE_DIR}/{name}'


def _materialize_images(
    item: PlanItem, zf: zipfile.ZipFile, *, lim: Limits, rewrite: bool
) -> str | None:
    """把包内插图重新校验+压缩后按内容寻址落盘。

    :param rewrite: 是否改写正文里与最终文件名不一致的 URL（skip 时无法改库，传 False）
    :return: 需要替换的正文（发生改写时），否则 None
    """
    entry = item.entry
    parsed = entry.parsed
    if not entry.images or parsed is None:
        return None

    mapping: dict[str, str] = {}
    for ref in entry.images:
        raw = _read_member(zf, ref.entry_name, settings.INLINE_IMAGE_MAX_BYTES)
        try:
            processed = process_inline_image(raw, ref.entry_name.rsplit('.', 1)[-1].lower())
        except InlineImageError as exc:
            raise ItemError(f'插图 {ref.name} 无法处理: {exc}') from None
        if processed.sha256 != ref.stored_sha256:
            raise ItemError(f'插图 {ref.name} 与校验阶段记录不一致')
        rel = store_inline_image(processed.data)
        new_name = os.path.basename(rel)
        if new_name != ref.name:
            mapping[_inline_url(ref.name)] = _inline_url(new_name)

    if not rewrite or not mapping:
        return None
    content = parsed.content
    for old, new in mapping.items():
        content = content.replace(old, new)
    return content if content != parsed.content else None


def _write_media(
    article: Article,
    item: PlanItem,
    *,
    lim: Limits,
    zf: zipfile.ZipFile,
    written: list[str],
    stale: list[str],
) -> tuple[set[str], str | None]:
    """落盘封面/附件（以及插图），返回（update_fields, 改写后的正文或 None）。"""
    fields: set[str] = set()
    entry = item.entry

    if item.replace_cover and entry.cover is not None:
        raw = _read_member(zf, entry.cover.entry_name, settings.COVER_MAX_BYTES)
        stored, stored_ext, _warnings = process_cover(raw, entry.cover.extension, lim)
        if sha256_bytes(stored) != entry.cover.stored_sha256:
            raise ItemError('封面与校验阶段记录不一致')
        stale.append(article.cover_image.name or '')
        # 封面统一压成 WebP，落盘扩展名恒为 webp：不能沿用包内 cover.jpg 的名字，
        # 否则会出现「.jpg 里装 WebP 字节」，nginx 会按扩展名发错 Content-Type
        article.cover_image.save(
            cover_upload_path(article, f'{COVER_BASENAME}.{stored_ext}'),
            ContentFile(stored),
            save=False,
        )
        article.cover_image_name = sanitize_original_name(
            entry.cover.original_name, entry.cover.entry_name
        )
        article.cover_image_sha256 = sha256_bytes(stored)
        written.append(article.cover_image.name or '')
        fields |= {'cover_image', 'cover_image_name', 'cover_image_sha256'}

    if item.replace_attachment and entry.attachment is not None:
        raw = _read_member(zf, entry.attachment.entry_name, settings.ATTACHMENT_MAX_BYTES)
        if sha256_bytes(raw) != entry.attachment.stored_sha256:
            raise ItemError('附件与校验阶段记录不一致')
        stale.append(article.file.name or '')
        article.file.save(
            file_upload_path(article, entry.attachment.entry_name),
            ContentFile(raw),
            save=False,
        )
        article.file_name = sanitize_original_name(
            entry.attachment.original_name, entry.attachment.entry_name
        )
        article.file_sha256 = sha256_bytes(raw)
        written.append(article.file.name or '')
        fields |= {'file', 'file_name', 'file_sha256'}

    content = _materialize_images(item, zf, lim=lim, rewrite=True)
    return fields, content


def _apply_metadata(
    article: Article, item: PlanItem, options: ImportOptions, *, creating: bool
) -> set[str]:
    """应用元数据字段；**只有 JSON 中存在的键才写入**（create 时写全量）。"""
    parsed = item.entry.parsed
    assert parsed is not None
    fields: set[str] = set()
    present = parsed.present

    if creating or 'title' in present:
        article.title = parsed.title
        fields.add('title')
    if creating or 'content' in present:
        article.content = parsed.content
        fields.add('content')
    if 'summary' in present:
        article.summary = parsed.summary
        fields.add('summary')
    if creating or 'publish_time' in present:
        article.publish_time = parsed.publish_time
        fields.add('publish_time')
    if 'location' in present:
        article.location = parsed.location
        fields.add('location')

    if creating:
        article.is_published = False if options.as_draft else bool(parsed.is_published)
        fields.add('is_published')
    elif 'is_published' in present:
        if options.as_draft:
            item.warnings.append('已开启"全部以草稿导入"，该篇为覆盖更新，已忽略该开关')
        else:
            article.is_published = bool(parsed.is_published)
            fields.add('is_published')

    return fields


def _materialize_skipped_images(item: PlanItem, zf: zipfile.ZipFile, lim: Limits) -> None:
    """``skip`` 也要补齐缺失的插图（换机/被 purge 后可重物化，幂等无副作用）。"""
    try:
        _materialize_images(item, zf, lim=lim, rewrite=False)
    except ItemError as exc:
        item.warnings.append(f'补齐插图失败（不影响跳过）: {exc.message}')


def execute_plan(
    plan: Plan,
    *,
    options: ImportOptions,
    package: dict,
    package_path: str | os.PathLike[str] | None = None,
) -> ImportReport:
    """真正执行计划。逐篇独立，失败不影响其它条目。

    ``package_path`` 为暂存包路径：校验阶段不驻留媒体字节，这里需要重开它取字节。
    """
    lim = plan.limits
    assert lim is not None
    user = options.user
    report = ImportReport()

    zf = zipfile.ZipFile(package_path) if package_path is not None else None
    try:
        for item in plan.items:
            entry = item.entry

            if item.action == 'failed':
                report.items.append(item.to_dict())
                continue
            if item.action == 'skip':
                if zf is not None:
                    _materialize_skipped_images(item, zf, lim)
                report.items.append(item.to_dict())
                continue
            if zf is None:
                raise ItemError('缺少暂存包路径，无法读取媒体字节')

            written: list[str] = []
            stale: list[str] = []
            try:
                with transaction.atomic():
                    parsed = entry.parsed
                    assert parsed is not None

                    category, _ = _resolve_category(parsed, options, item.warnings)
                    tags, _ = _resolve_tags(parsed, options, item.warnings)

                    if item.action == 'create':
                        article = Article(
                            slug=item.final_slug or unique_slug(parsed.slug),
                            author=user,
                            category=category,
                            cover_image_name='',
                            file_name='',
                        )
                        fields = _apply_metadata(article, item, options, creating=True)
                        media_fields, content_override = _write_media(
                            article, item, lim=lim, zf=zf, written=written, stale=[]
                        )
                        fields |= media_fields
                        if content_override is not None:
                            article.content = content_override
                        article.save()
                        article.tags.set(tags)
                        item.target_id = article.id
                    else:
                        if item.target_id is None:
                            raise IntegrityError('目标文章缺失')
                        existing = Article.objects.filter(pk=item.target_id).first()
                        if existing is None:  # 计划生成后被删除
                            raise IntegrityError('目标文章已不存在')
                        fields = _apply_metadata(existing, item, options, creating=False)
                        if 'slug' in parsed.present:
                            existing.slug = unique_slug(parsed.slug, exclude_id=existing.pk)
                            fields.add('slug')
                        if parsed.category is not None or 'category' in parsed.present:
                            existing.category = category
                            fields.add('category')
                        media_fields, content_override = _write_media(
                            existing, item, lim=lim, zf=zf, written=written, stale=stale
                        )
                        fields |= media_fields
                        if content_override is not None:
                            existing.content = content_override
                            fields.add('content')
                        if fields:
                            existing.save(update_fields=fields | {'updated_at'})
                        if 'tags' in parsed.present:
                            existing.tags.set(tags)

                # 事务提交后再删除被替换掉的旧文件（插图不删：可能被别的文章共用）
                _delete_files(stale)
                report.items.append(item.to_dict())
            except Exception as exc:
                _delete_files(written)
                logger.warning(
                    '归档导入条目失败 path=%s: %s', entry.dir_path, exc, exc_info=True
                )
                item.action = 'failed'
                item.errors.append(f'导入失败: {type(exc).__name__}')
                report.items.append(item.to_dict())
    finally:
        if zf is not None:
            zf.close()

    return report
