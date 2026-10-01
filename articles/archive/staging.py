"""暂存包与下载票据的生命周期管理。

- 所有产物落在 ``ARCHIVE_ROOT``（**不得**位于对外服务的 media/static 下）。
- 票据 id 即 URL 中的 ticket（能力 URL，不绑定 owner —— 方案 P1-A 的已知取舍）。
- 清扫一律**先删文件再删行**，并跳过带"使用中租约"的暂存目录。
"""
import logging
import shutil
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from .errors import PackageError
from .limits import limits

if TYPE_CHECKING:
    from articles.models import ArchiveTicket

logger = logging.getLogger(__name__)

STAGING_DIR = 'staging'
EXPORTS_DIR = 'exports'
ROLLBACKS_DIR = 'rollbacks'


def archive_root() -> Path:
    """归档根目录（不存在则创建）。"""
    root = Path(limits().root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def ensure_subdirs() -> Path:
    """确保三个子目录存在。"""
    root = archive_root()
    for name in (STAGING_DIR, EXPORTS_DIR, ROLLBACKS_DIR):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def _rel(path: Path) -> str:
    return str(path.relative_to(archive_root()))


def rel_path(path) -> str:
    """公开版本：把归档目录转成相对 ARCHIVE_ROOT 的路径（存库用）。"""
    return _rel(Path(path))


def _safe_under_root(relative: str) -> Path:
    """把库里的相对路径还原成绝对路径，并断言仍在 ARCHIVE_ROOT 内。"""
    root = archive_root().resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise PackageError('归档路径非法')
    return target


# --------------------------------------------------------------------------- 暂存


def create_staging_dir(staging_id) -> Path:
    """为某次上传创建暂存目录。"""
    path = archive_root() / STAGING_DIR / str(staging_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def staging_path(relative_dir: str) -> Path:
    """暂存目录的绝对路径。"""
    return _safe_under_root(relative_dir)


def staging_archive_path(staging) -> Path:
    """暂存包内 zip 的绝对路径。"""
    return staging_path(staging.dir) / 'package.zip'


# --------------------------------------------------------------------------- 票据


def create_ticket(*, user, kind: str, path: Path, filename: str, size: int) -> 'ArchiveTicket':
    """登记一张一次性下载票据。"""
    from articles.models import ArchiveTicket

    cfg = limits()
    return ArchiveTicket.objects.create(
        user=user,
        kind=kind,
        path=_rel(path),
        filename=filename,
        bytes=size,
        expires_at=timezone.now() + timedelta(seconds=cfg.ticket_ttl),
    )


def claim_ticket(ticket_id) -> 'ArchiveTicket | None':
    """原子占用票据：只有把 used_at 从 NULL 改成时间的那一次请求能拿到。

    ``rowcount != 1`` → 已用或已过期，调用方返回 404/410。
    """
    from articles.models import ArchiveTicket

    now = timezone.now()
    updated = ArchiveTicket.objects.filter(
        id=ticket_id, used_at__isnull=True, expires_at__gt=now
    ).update(used_at=now)
    if updated != 1:
        return None
    ticket = ArchiveTicket.objects.filter(id=ticket_id).first()
    return ticket


def ticket_file(ticket) -> Path:
    """票据对应的磁盘文件；文件缺失时抛 PackageError。"""
    path = _safe_under_root(ticket.path)
    if not path.exists():
        raise PackageError('归档文件已过期或被清理，请重新生成')
    return path


def reissue_ticket(ticket) -> 'ArchiveTicket':
    """重签：把一张已用/将过期的票据换成新的有效期。"""

    cfg = limits()
    with transaction.atomic():
        ticket.used_at = None
        ticket.expires_at = timezone.now() + timedelta(seconds=cfg.ticket_ttl)
        ticket.save(update_fields=['used_at', 'expires_at'])
    return ticket


def is_uuid(value: str) -> bool:
    """判断路径段是否是合法 UUID（避免把非法 ticket 交给 ORM）。"""
    try:
        UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return False
    return True


# --------------------------------------------------------------------------- 清扫


def sweep(*, now=None) -> dict:
    """清理过期的暂存目录、导出/回滚产物与过期行。

    - 先删文件再删行；
    - 跳过带"使用中租约"的暂存目录（避免把正在 commit 的暂存删掉）。
    """
    from articles.models import ArchiveStaging, ArchiveTicket

    moment = now or timezone.now()
    removed = {'staging': 0, 'files': 0, 'tickets': 0, 'stagings': 0}

    for staging in ArchiveStaging.objects.filter(expires_at__lte=moment):
        if staging.lease_until and staging.lease_until > moment:
            continue  # 正在被使用
        path = _safe_under_root(staging.dir)
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
            removed['staging'] += 1
        staging.delete()
        removed['stagings'] += 1

    for ticket in ArchiveTicket.objects.filter(expires_at__lte=moment):
        path = _safe_under_root(ticket.path)
        if path.exists():
            path.unlink(missing_ok=True)
            removed['files'] += 1
        ticket.delete()
        removed['tickets'] += 1

    # 兜底：清理没有 DB 行对应的孤儿产物（例如写完文件就崩溃、或行被手工删过）
    root = archive_root()
    known = set(
        ArchiveTicket.objects.values_list('path', flat=True)
    ) | set(ArchiveStaging.objects.values_list('dir', flat=True))
    stamp = timezone.now().timestamp()
    for sub in (EXPORTS_DIR, ROLLBACKS_DIR):
        for path in (root / sub).glob('*'):
            if path.is_file() and _rel(path) not in known:
                if stamp - path.stat().st_mtime > 3600:
                    path.unlink(missing_ok=True)
                    removed['files'] += 1
    # 孤儿暂存**目录**（没有对应 ArchiveStaging 行）同样回收，否则会永久占盘
    for path in (root / STAGING_DIR).glob('*'):
        if path.is_dir() and _rel(path) not in known:
            if stamp - path.stat().st_mtime > 3600:
                shutil.rmtree(path, ignore_errors=True)
                removed['staging'] += 1

    return removed
