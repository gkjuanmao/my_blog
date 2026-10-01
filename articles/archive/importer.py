"""执行计划：写库、落盘媒体、失败补偿。

关键不变量：
- 每篇一个 ``transaction.atomic()``（分类/标签的自动创建也在同一保存点内，失败一起回滚）。
- 媒体落盘**不在事务内**，因此显式记录本次写入的文件名，异常时逐个回收。
- update 一律 ``save(update_fields=...)``，且**永不读写** views/created_at/updated_at/author。
- ``as_draft`` 只作用于 create（决策 D22），对 update 忽略并告警。
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction

from articles.models import Article, Category, Tag
from articles.utils import unique_slug

from .format import sha256_bytes
from .limits import Limits
from .planner import Plan, PlanItem

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
            'schema': 'myblog.archive/v1',
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


def _write_media(
    article: Article,
    item: PlanItem,
    *,
    lim: Limits,
    written: list[str],
    stale: list[str],
) -> set[str]:
    """落盘封面/附件，返回需要写入的 update_fields。"""
    from articles.models import cover_upload_path, file_upload_path

    fields: set[str] = set()
    entry = item.entry

    if item.replace_cover and entry.cover is not None:
        # 校验阶段已决定存储字节（规范格式原样存、否则重编码），这里不重复处理
        stored = entry.cover.stored_bytes or entry.cover.data
        stale.append(article.cover_image.name or '')
        article.cover_image.save(
            cover_upload_path(article, entry.cover.entry_name),
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
        stored = entry.attachment.stored_bytes or entry.attachment.data
        stale.append(article.file.name or '')
        article.file.save(
            file_upload_path(article, entry.attachment.entry_name),
            ContentFile(stored),
            save=False,
        )
        article.file_name = sanitize_original_name(
            entry.attachment.original_name, entry.attachment.entry_name
        )
        article.file_sha256 = sha256_bytes(stored)
        written.append(article.file.name or '')
        fields |= {'file', 'file_name', 'file_sha256'}

    return fields


def _apply_metadata(
    article: Article, item: PlanItem, options: ImportOptions, *, creating: bool
) -> set[str]:
    """应用元数据字段；**只有 JSON 中存在的键才写入**。"""
    parsed = item.entry.parsed
    assert parsed is not None
    fields: set[str] = set()
    present = parsed.present

    if creating or 'title' in present:
        article.title = parsed.title
        fields.add('title')
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


def execute_plan(plan: Plan, *, options: ImportOptions, package: dict) -> ImportReport:
    """真正执行计划。逐篇独立，失败不影响其它条目。"""
    lim = plan.limits
    assert lim is not None
    user = options.user
    report = ImportReport()

    for item in plan.items:
        entry = item.entry

        if item.action in ('skip', 'failed'):
            report.items.append(item.to_dict())
            continue

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
                    fields |= _write_media(article, item, lim=lim, written=written, stale=[])
                    # 新建：先写库再 tags.set（M2M 需要 pk）
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
                    fields |= _write_media(
                        existing, item, lim=lim, written=written, stale=stale
                    )
                    if fields:
                        existing.save(update_fields=fields | {'updated_at'})
                    if 'tags' in parsed.present:
                        existing.tags.set(tags)

            # 事务提交后再删除被替换掉的旧文件
            _delete_files(stale)
            item.action = 'create' if item.action == 'create' else 'update'
            report.items.append(item.to_dict())
        except Exception as exc:
            _delete_files(written)
            logger.warning('归档导入条目失败 path=%s: %s', entry.dir_path, exc, exc_info=True)
            item.action = 'failed'
            item.errors.append(f'导入失败: {type(exc).__name__}')
            report.items.append(item.to_dict())

    return report
