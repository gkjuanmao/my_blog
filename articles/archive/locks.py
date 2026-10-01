"""导入串行锁与最小间隔（缓存实现，**fail-closed**）。

为什么不用 ``select_for_update``：SQLite 上 ``has_select_for_update`` 为 False，
Django 会**静默丢弃** ``FOR UPDATE``（实测），锁等于不存在。因此在缓存上做
``add``（SET NX + TTL）实现的单写者锁，并带 owner token 防误删。

缓存（prod 为 Redis）不可用时返回 503 而不是静默放行——否则并发导入会同时写库。
"""
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from django.core.cache import cache

from .errors import ConflictError, LockUnavailable, RateLimitedError
from .limits import Limits, limits

logger = logging.getLogger(__name__)

GLOBAL_LOCK_KEY = 'archive:import:lock'
INTERVAL_KEY = 'archive:import:interval:{user_id}'


def _acquire(key: str, token: str, ttl: int) -> bool:
    """``cache.add`` 即 SET NX：返回是否拿到。"""
    try:
        return bool(cache.add(key, token, ttl))
    except Exception as exc:
        logger.warning('归档锁缓存不可用: %s', exc)
        raise LockUnavailable('导入锁不可用，请稍后重试') from None


def _release(key: str, token: str) -> None:
    """仅释放自己持有的锁（比对 token 后再删）。"""
    try:
        if cache.get(key) == token:
            cache.delete(key)
    except Exception:  # pragma: no cover - 缓存故障时交给 TTL 自解
        logger.warning('归档锁释放失败，将由 TTL 自动过期', exc_info=True)


@contextmanager
def import_lock(lim: Limits | None = None) -> Iterator[None]:
    """全局单写者导入锁（带 TTL，进程被杀后自动过期）。"""
    cfg = lim or limits()
    token = uuid.uuid4().hex
    if not _acquire(GLOBAL_LOCK_KEY, token, cfg.lock_ttl):
        raise ConflictError('已有导入任务在进行中，请稍后重试')
    try:
        yield
    finally:
        _release(GLOBAL_LOCK_KEY, token)


def enforce_min_interval(user_id: int, lim: Limits | None = None) -> None:
    """同一用户两次导入的最小间隔。"""
    cfg = lim or limits()
    if cfg.import_min_interval <= 0:
        return
    key = INTERVAL_KEY.format(user_id=user_id)
    if not _acquire(key, uuid.uuid4().hex, cfg.import_min_interval):
        raise RateLimitedError('导入过于频繁，请稍后再试')
