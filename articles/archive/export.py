"""导出：选择文章、可回导性校验、打包与预估。

**唯一 builder**：正式导出与回滚包共用 ``_build_archive``（仅 ``import.action`` 不同），
避免两处实现分叉导致回滚包漏掉 content / images。
"""
import json
import logging
import os
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import django
from django.conf import settings
from django.core.files.storage import default_storage
from django.utils import timezone

from articles.images import extract_inline_names
from articles.models import Article
from articles.rendering import render_markdown
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
    images_entry_name,
    sha256_bytes,
)
from .limits import Limits, import_capacity_blockers, limits

logger = logging.getLogger(__name__)

APP_VERSION = '0.1.0'

# 预估阶段用等长的占位哈希，保证 JSON 字节数与真实导出完全一致（口径同源）
_SHA_PLACEHOLDER = '0' * 64

# 固定成员：manifest.json + README.md
FIXED_ENTRIES = 2


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


def _file_meta(
    field,
    *,
    entry_name: str,
    original_name: str,
    read_bytes: bool,
) -> tuple[dict | None, tuple[str, bytes] | None, bool]:
    """返回 ``(meta, blob, missing)``。

    ``missing`` 仅在"字段有文件名但磁盘上读不到"时为 True（文章本就没有该附件不算缺失）。
    """
    name = getattr(field, 'name', '') or ''
    if not name:
        return None, None, False
    try:
        if not default_storage.exists(name):
            return None, None, True
        if read_bytes:
            with default_storage.open(name, 'rb') as handle:
                data = handle.read()
            size = len(data)
            digest = sha256_bytes(data)
            blob: tuple[str, bytes] | None = (entry_name, data)
        else:
            size = default_storage.size(name)
            digest = _SHA_PLACEHOLDER
            blob = None
    except OSError:  # pragma: no cover - 存储异常
        return None, None, True
    meta = {
        'file': entry_name,
        'original_name': original_name,
        'sha256': digest,
        'size': size,
    }
    return meta, blob, False


def _inline_dir() -> str:
    return os.path.join(str(settings.MEDIA_ROOT), settings.INLINE_IMAGE_DIR)


def _scan_inline_images(
    article: Article, *, read_bytes: bool, warnings: list[str]
) -> tuple[list[dict], list[tuple[str, bytes]]]:
    """收集正文引用的内联图（从**渲染消毒后的 HTML** 提取，与 purge 同一实现）。"""
    names = sorted(extract_inline_names(render_markdown(article.content)))
    metas: list[dict] = []
    blobs: list[tuple[str, bytes]] = []
    directory = _inline_dir()
    for name in names:
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            warnings.append(f'《{article.title}》正文引用的插图 {name} 在磁盘上缺失')
            continue
        entry_name = images_entry_name(name)
        if read_bytes:
            with open(path, 'rb') as handle:
                data = handle.read()
            metas.append({
                'file': entry_name,
                'sha256': sha256_bytes(data),
                'size': len(data),
            })
            blobs.append((entry_name, data))
        else:
            metas.append({
                'file': entry_name,
                'sha256': _SHA_PLACEHOLDER,
                'size': os.path.getsize(path),
            })
    return metas, blobs


def _scan_article(
    article: Article, *, read_bytes: bool, action: str = 'auto'
) -> tuple[dict, list[tuple[str, bytes]], list[str]]:
    """产出一篇文章的 article.json payload 与待写入的成员（含生成型 JSON 的字节数）。"""
    warnings: list[str] = []

    cover_meta, cover_blob, cover_missing = _file_meta(
        article.cover_image,
        entry_name=cover_entry_name(extension_of(article.cover_image.name)),
        original_name=article.cover_image_name,
        read_bytes=read_bytes,
    )
    if cover_missing:
        warnings.append(f'《{article.title}》的封面在磁盘上缺失，导入前需补齐')

    attachment_entry = attachment_entry_name(extension_of(article.file.name))
    attachment_meta, attachment_blob, attachment_missing = _file_meta(
        article.file,
        entry_name=attachment_entry,
        original_name=article.file_name,
        read_bytes=read_bytes,
    )
    if attachment_missing:
        warnings.append(f'《{article.title}》的附件在磁盘上缺失，导入前需补齐')

    images_meta, image_blobs = _scan_inline_images(
        article, read_bytes=read_bytes, warnings=warnings
    )

    payload = build_article_json(
        article,
        cover=cover_meta,
        attachment=attachment_meta,
        images=images_meta,
        exported_at=timezone.now(),
        app_version=APP_VERSION,
        import_action=action,
    )
    blobs: list[tuple[str, bytes]] = []
    if cover_blob:
        blobs.append(cover_blob)
    if attachment_blob:
        blobs.append(attachment_blob)
    blobs.extend(image_blobs)
    return payload, blobs, warnings


def _serialize(payload: dict) -> bytes:
    """与导出完全一致的 JSON 序列化（预估与打包共用，避免字节口径分叉）。"""
    return (json.dumps(payload, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def estimate_export(articles: list[Article], *, lim: Limits | None = None) -> ExportEstimate:
    """统计条目数/字节，并给出"不可回导"的原因（与导入校验同口径）。"""
    cfg = lim or limits()
    result = ExportEstimate(count=len(articles), entries=FIXED_ENTRIES)
    for article in articles:
        payload, _blobs, warnings = _scan_article(article, read_bytes=False)
        result.warnings.extend(warnings)
        # 每篇实际成员：article.json + 封面? + 附件? + 内联图*
        result.entries += 1 + (1 if payload['cover'] else 0)
        result.entries += 1 if payload['attachment'] else 0
        result.entries += len(payload['images'])
        # 字节：生成型成员（article.json）用真实序列化长度 + 磁盘媒体真实字节
        result.source_bytes += len(_serialize(payload))
        for meta in (payload['cover'], payload['attachment'], *payload['images']):
            if meta:
                result.source_bytes += meta['size']
    # manifest.json / README.md 也是包内成员（导入侧 _check_infos 按全部文件计数）
    result.source_bytes += len(README_TEMPLATE.encode('utf-8')) + 4096
    result.blocking_reasons = import_capacity_blockers(
        article_count=result.count,
        entries=result.entries,
        source_bytes=result.source_bytes,
        # zip 已压缩，按源字节估计上界（与导入侧同一组上限比较）
        zip_bytes=result.source_bytes,
        lim=cfg,
    )
    return result


def _build_archive(
    articles: list[Article],
    out_path: Path,
    *,
    action: str,
    lim: Limits | None = None,
    check_capacity: bool = True,
) -> dict:
    """把文章写成一个 zip（正式导出与回滚包共用）；返回 {count, bytes, warnings}。"""
    cfg = lim or limits()
    estimate = estimate_export(articles, lim=cfg) if check_capacity else None
    if estimate is not None and estimate.blocking_reasons:
        raise PackageError('导出范围超出导入上限：' + '；'.join(estimate.blocking_reasons))

    exported_at = timezone.now()
    manifest_articles: list[dict] = []
    warnings: list[str] = []

    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for index, article in enumerate(articles, start=1):
            dir_name = f'{ARTICLES_DIR}/{article_dir_name(index, article.slug)}'
            payload, blobs, article_warnings = _scan_article(
                article, read_bytes=True, action=action
            )
            warnings.extend(article_warnings)

            for entry_name, data in blobs:
                zf.writestr(f'{dir_name}/{entry_name}', data)
            zf.writestr(f'{dir_name}/article.json', _serialize(payload))

            manifest_articles.append({
                'index': index,
                'path': dir_name,
                'slug': article.slug,
                'title': article.title,
                'is_published': article.is_published,
                'updated_at': article.updated_at.isoformat(),
            })

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

    return {
        'count': len(articles),
        'bytes': out_path.stat().st_size,
        'warnings': warnings,
    }


def build_archive(articles: list[Article], out_path: Path, *, lim: Limits | None = None) -> dict:
    """正式导出（import.action=auto，带可回导性校验）。"""
    return _build_archive(articles, out_path, action='auto', lim=lim, check_capacity=True)


def build_archive_with_action(
    articles: list[Article], out_path: Path, *, action: str, lim: Limits | None = None
) -> dict:
    """可控 ``import.action`` 的打包（内部复用同一 builder）。"""
    return _build_archive(articles, out_path, action=action, lim=lim, check_capacity=False)


def export_filename(moment: datetime | None = None) -> str:
    """纯 ASCII 下载文件名（避免 RFC 5987 兼容问题）。"""
    stamp = (moment or timezone.now()).strftime('%Y%m%d-%H%M%S')
    return f'articles-{stamp}.zip'


def build_rollback_archive(
    articles: list[Article], out_path: Path, *, lim: Limits | None = None
) -> dict:
    """生成回滚包：内容为受影响文章的**前态**（含正文与插图），强制 ``action=update``。

    关键：若写成 ``auto``，用默认策略重导会全部跳过 → 回滚包形同废纸。
    """
    return build_archive_with_action(articles, out_path, action='update', lim=lim)


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
