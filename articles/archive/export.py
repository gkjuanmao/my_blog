"""导出：选择文章、可回导性校验、打包与预估。"""
import json
import logging
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import django
from django.core.files.storage import default_storage
from django.utils import timezone

from articles.models import Article
from articles.utils import generate_slug

from .errors import PackageError
from .format import (
    ARTICLES_DIR,
    MANIFEST_NAME,
    README_NAME,
    README_TEMPLATE,
    article_dir_name,
    attachment_entry_name,
    build_article_json,
    build_manifest,
    cover_entry_name,
    extension_of,
    sha256_bytes,
)
from .limits import Limits, import_capacity_blockers, limits

logger = logging.getLogger(__name__)

APP_VERSION = '0.1.0'


@dataclass
class ExportEstimate:
    """导出预估（也作为"能否回导"的判定结果）。"""

    count: int = 0
    source_bytes: int = 0
    entries: int = 0
    warnings: list[str] = field(default_factory=list)
    blocking_reasons: list[str] = field(default_factory=list)

    @property
    def importable(self) -> bool:
        return not self.blocking_reasons

    def to_dict(self) -> dict:
        return {
            'count': self.count,
            'source_bytes': self.source_bytes,
            'entries': self.entries,
            'importable': self.importable,
            'blocking_reasons': self.blocking_reasons,
            'warnings': self.warnings,
        }


def select_articles(
    *,
    ids: list[int] | None = None,
    keyword: str = '',
    category_slug: str = '',
    is_published: bool | None = None,
) -> list[Article]:
    """按 id 或列表筛选条件取文章；导出顺序固定 publish_time DESC, id DESC。"""
    qs = Article.objects.select_related('author', 'category').prefetch_related('tags')
    if ids:
        qs = qs.filter(pk__in=ids)
    else:
        if keyword:
            qs = qs.filter(title__icontains=keyword)
        if category_slug:
            qs = qs.filter(category__slug=category_slug)
        if is_published is not None:
            qs = qs.filter(is_published=is_published)
    # -id 次要键：publish_time 相同时保证 NNN 序号稳定
    return list(qs.order_by('-publish_time', '-id'))


def _read_stored(image_field) -> bytes | None:
    """读取 FileField 背后的字节；文件缺失返回 None（导出侧只告警不失败）。"""
    if not image_field:
        return None
    name = image_field.name
    if not name:
        return None
    try:
        if not default_storage.exists(name):
            return None
        with default_storage.open(name, 'rb') as handle:
            return handle.read()
    except OSError:  # pragma: no cover - 存储异常
        return None


def estimate_export(articles: list[Article], *, lim: Limits | None = None) -> ExportEstimate:
    """统计条目数/源字节，并给出"不可回导"的原因。"""
    cfg = lim or limits()
    result = ExportEstimate(count=len(articles), entries=len(articles) * 3)
    for article in articles:
        for image_field in (article.cover_image, article.file):
            name = getattr(image_field, 'name', '')
            if not name or not default_storage.exists(name):
                result.warnings.append(f'《{article.title}》的媒体文件在磁盘上缺失，导入前需补齐')
                continue
            try:
                result.source_bytes += default_storage.size(name)
            except OSError:  # pragma: no cover
                result.warnings.append(f'《{article.title}》的媒体文件无法读取')
    result.blocking_reasons = import_capacity_blockers(
        article_count=result.count,
        source_bytes=result.source_bytes,
        # zip 已压缩，按源字节估计上界（与导入侧同一组上限比较）
        zip_bytes=result.source_bytes,
        lim=cfg,
    )
    return result


def build_archive(articles: list[Article], out_path: Path, *, lim: Limits | None = None) -> dict:
    """把文章写成一个 zip；返回 {count, bytes, warnings}。"""
    cfg = lim or limits()
    estimate = estimate_export(articles, lim=cfg)
    if estimate.blocking_reasons:
        raise PackageError('导出范围超出导入上限：' + '；'.join(estimate.blocking_reasons))

    exported_at = timezone.now()
    manifest_articles: list[dict] = []
    manifest_warnings = list(estimate.warnings)

    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for index, article in enumerate(articles, start=1):
            dir_name = f'{ARTICLES_DIR}/{article_dir_name(index, article.slug)}'
            cover_meta = None
            attachment_meta = None

            cover_bytes = _read_stored(article.cover_image)
            if cover_bytes is not None:
                ext = extension_of(article.cover_image.name)
                entry_name = cover_entry_name(ext)
                zf.writestr(f'{dir_name}/{entry_name}', cover_bytes)
                cover_meta = {
                    'file': entry_name,
                    'original_name': article.cover_image_name,
                    'sha256': sha256_bytes(cover_bytes),
                    'size': len(cover_bytes),
                }

            attachment_bytes = _read_stored(article.file)
            if attachment_bytes is not None:
                ext = extension_of(article.file.name)
                entry_name = attachment_entry_name(ext)
                zf.writestr(f'{dir_name}/{entry_name}', attachment_bytes)
                attachment_meta = {
                    'file': entry_name,
                    'original_name': article.file_name,
                    'sha256': sha256_bytes(attachment_bytes),
                    'size': len(attachment_bytes),
                }

            payload = build_article_json(
                article,
                cover=cover_meta,
                attachment=attachment_meta,
                exported_at=exported_at,
                app_version=APP_VERSION,
            )
            zf.writestr(
                f'{dir_name}/article.json',
                json.dumps(payload, ensure_ascii=False, indent=2) + '\n',
            )
            manifest_articles.append(
                {
                    'index': index,
                    'path': dir_name,
                    'slug': article.slug,
                    'title': article.title,
                    'is_published': article.is_published,
                    'updated_at': article.updated_at.isoformat(),
                }
            )

        manifest = build_manifest(
            exported_at=exported_at,
            app_version=APP_VERSION,
            django_version=django.get_version(),
            filters={'ids': [a.id for a in articles], 'count': len(articles)},
            articles=manifest_articles,
            warnings=manifest_warnings,
            limits_snapshot={
                'max_member_bytes': cfg.max_member_bytes,
                'max_total_uncompressed': cfg.max_total_uncompressed,
                'max_entries': cfg.max_entries,
            },
        )
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        zf.writestr(README_NAME, README_TEMPLATE)

    return {
        'count': len(articles),
        'bytes': out_path.stat().st_size,
        'warnings': manifest_warnings,
    }


def export_filename(moment: datetime | None = None) -> str:
    """纯 ASCII 下载文件名（避免 RFC 5987 兼容问题）。"""
    stamp = (moment or timezone.now()).strftime('%Y%m%d-%H%M%S')
    return f'articles-{stamp}.zip'


def build_rollback_archive(
    articles: list[Article], out_path: Path, *, lim: Limits | None = None
) -> dict:
    """生成回滚包：内容为受影响文章的**前态**，内部强制 ``import.action=update``。

    关键：若写成 ``auto``，用默认策略重导会全部跳过 → 回滚包形同废纸。
    """
    cfg = lim or limits()
    result = build_archive_with_action(articles, out_path, action='update', lim=cfg)
    return result


def build_archive_with_action(
    articles: list[Article], out_path: Path, *, action: str, lim: Limits | None = None
) -> dict:
    """与 ``build_archive`` 相同，但可控 article.json 内的 import.action。"""
    cfg = lim or limits()
    if action == 'auto':
        return build_archive(articles, out_path, lim=cfg)

    # 复用 build_archive 的逻辑：临时替换 article.json 的 action
    exported_at = timezone.now()
    manifest_articles: list[dict] = []
    warnings: list[str] = []
    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for index, article in enumerate(articles, start=1):
            dir_name = f'{ARTICLES_DIR}/{article_dir_name(index, article.slug)}'
            cover_meta = None
            attachment_meta = None
            cover_bytes = _read_stored(article.cover_image)
            if cover_bytes is not None:
                ext = extension_of(article.cover_image.name)
                entry_name = cover_entry_name(ext)
                zf.writestr(f'{dir_name}/{entry_name}', cover_bytes)
                cover_meta = {
                    'file': entry_name,
                    'original_name': article.cover_image_name,
                    'sha256': sha256_bytes(cover_bytes),
                    'size': len(cover_bytes),
                }
            attachment_bytes = _read_stored(article.file)
            if attachment_bytes is not None:
                ext = extension_of(article.file.name)
                entry_name = attachment_entry_name(ext)
                zf.writestr(f'{dir_name}/{entry_name}', attachment_bytes)
                attachment_meta = {
                    'file': entry_name,
                    'original_name': article.file_name,
                    'sha256': sha256_bytes(attachment_bytes),
                    'size': len(attachment_bytes),
                }
            payload = build_article_json(
                article,
                cover=cover_meta,
                attachment=attachment_meta,
                exported_at=exported_at,
                app_version=APP_VERSION,
                import_action=action,
            )
            zf.writestr(
                f'{dir_name}/article.json',
                json.dumps(payload, ensure_ascii=False, indent=2) + '\n',
            )
            manifest_articles.append(
                {
                    'index': index,
                    'path': dir_name,
                    'slug': article.slug,
                    'title': article.title,
                    'is_published': article.is_published,
                    'updated_at': article.updated_at.isoformat(),
                }
            )
        manifest = build_manifest(
            exported_at=exported_at,
            app_version=APP_VERSION,
            django_version=django.get_version(),
            filters={'ids': [a.id for a in articles], 'count': len(articles)},
            articles=manifest_articles,
            warnings=warnings,
            limits_snapshot={
                'max_member_bytes': cfg.max_member_bytes,
                'max_total_uncompressed': cfg.max_total_uncompressed,
                'max_entries': cfg.max_entries,
            },
        )
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        zf.writestr(README_NAME, README_TEMPLATE)
    return {'count': len(articles), 'bytes': out_path.stat().st_size, 'warnings': warnings}


__all__ = [
    'ExportEstimate',
    'build_archive',
    'build_archive_with_action',
    'build_rollback_archive',
    'estimate_export',
    'export_filename',
    'generate_slug',
    'select_articles',
]
