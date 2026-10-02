"""归档上限的**调用时**读取与磁盘空间预检。

为什么不在模块级固化常量：项目用 ``override_settings`` 在测试里把上限收紧到极小值
来覆盖 400/413 分支，模块级固化会让这些测试失效。
"""
import shutil
from dataclasses import dataclass

from django.conf import settings

from .errors import LimitExceeded, PackageError


@dataclass(frozen=True)
class Limits:
    """一次归档操作生效的上限快照。"""

    root: str
    staging_ttl: int
    ticket_ttl: int
    import_min_interval: int
    lock_ttl: int
    max_upload_bytes: int
    max_entries: int
    max_total_uncompressed: int
    max_member_bytes: int
    max_compression_ratio: int
    max_path_length: int
    max_depth: int
    max_json_bytes: int
    max_articles_per_export: int
    max_ids_per_request: int
    max_new_categories: int
    max_new_tags: int
    max_image_pixels: int


def limits() -> Limits:
    """读取当前生效的上限（每次调用都重新读 settings）。"""
    return Limits(
        root=str(settings.ARCHIVE_ROOT),
        staging_ttl=int(settings.ARCHIVE_STAGING_TTL_SECONDS),
        ticket_ttl=int(settings.ARCHIVE_TICKET_TTL_SECONDS),
        import_min_interval=int(settings.ARCHIVE_IMPORT_MIN_INTERVAL_SECONDS),
        lock_ttl=int(settings.ARCHIVE_LOCK_TTL_SECONDS),
        max_upload_bytes=int(settings.ARCHIVE_MAX_UPLOAD_BYTES),
        max_entries=int(settings.ARCHIVE_MAX_ENTRIES),
        max_total_uncompressed=int(settings.ARCHIVE_MAX_TOTAL_UNCOMPRESSED),
        max_member_bytes=int(settings.ARCHIVE_MAX_MEMBER_BYTES),
        max_compression_ratio=int(settings.ARCHIVE_MAX_COMPRESSION_RATIO),
        max_path_length=int(settings.ARCHIVE_MAX_PATH_LENGTH),
        max_depth=int(settings.ARCHIVE_MAX_DEPTH),
        max_json_bytes=int(settings.ARCHIVE_MAX_JSON_BYTES),
        max_articles_per_export=int(settings.ARCHIVE_MAX_ARTICLES_PER_EXPORT),
        max_ids_per_request=int(settings.ARCHIVE_MAX_IDS_PER_REQUEST),
        max_new_categories=int(settings.ARCHIVE_MAX_NEW_CATEGORIES),
        max_new_tags=int(settings.ARCHIVE_MAX_NEW_TAGS),
        max_image_pixels=int(settings.ARCHIVE_MAX_IMAGE_PIXELS),
    )


def import_capacity_blockers(
    *,
    article_count: int,
    entries: int,
    source_bytes: int,
    zip_bytes: int,
    lim: Limits | None = None,
) -> list[str]:
    """返回"该包不可能被本系统导入"的原因列表（导出侧的可回导性校验）。

    ⚠️ ``entries`` 必须是**实际条目数**（含固定成员 manifest/README 与每张内联图），
    不能再用"篇数 × 固定值"估算：正文与内联图让每篇的条目数不再固定，估算会产出
    "导出成功但导入被拒"的包。

    ``article_count`` 只是一道粗过滤；真正的门禁是 ``entries`` 与 ``source_bytes``
    （与导入侧 ``_check_infos`` / ``budget`` 同口径）。
    """
    cfg = lim or limits()
    reasons: list[str] = []
    if article_count > cfg.max_articles_per_export:
        reasons.append(f'文章数 {article_count} 超过单次导出上限 {cfg.max_articles_per_export}')
    if entries > cfg.max_entries:
        reasons.append(f'预计条目数 {entries} 超过导入上限 {cfg.max_entries} 条')
    if source_bytes > cfg.max_total_uncompressed:
        reasons.append(
            f'源文件总字节 {source_bytes} 超过导入解压上限 {cfg.max_total_uncompressed}'
        )
    if zip_bytes > cfg.max_upload_bytes:
        reasons.append(f'预计包体积 {zip_bytes} 超过导入上传上限 {cfg.max_upload_bytes}')
    return reasons


def _existing_anchor(path: str) -> str | None:
    """找到最近的**已存在**的祖先目录（目录尚未创建时也能查磁盘）。"""
    from pathlib import Path

    candidate = Path(path)
    while True:
        if candidate.exists():
            return str(candidate)
        if candidate.parent == candidate:
            return None
        candidate = candidate.parent


def ensure_free_space(*, needed_bytes: int, extra_dirs: tuple[str, ...] = ()) -> None:
    """检查上传暂存目录与归档目录是否有足够空间。

    needed_bytes 为**本次操作预计写入**的字节数。阈值取 1.5 倍余量。
    目录尚未创建时向上找最近的已存在祖先，避免直接报错。
    """
    cfg = limits()
    required = int(needed_bytes * 1.5)
    targets = list(extra_dirs) + [cfg.root, str(settings.FILE_UPLOAD_TEMP_DIR or '')]
    for target in targets:
        if not target:
            continue
        anchor = _existing_anchor(target)
        if anchor is None:
            raise PackageError(f'归档目录不可用: {target}')
        try:
            usage = shutil.disk_usage(anchor)
        except OSError as exc:
            raise PackageError(f'归档目录不可用: {exc}') from None
        if usage.free < required:
            raise LimitExceeded(
                f'磁盘空间不足：{anchor} 剩余 {usage.free} 字节，本次需要约 {required} 字节'
            )
