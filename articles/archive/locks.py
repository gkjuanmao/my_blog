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
def import_lock(lim: Limits | None = None) -> Iterator['LockHandle']:
    """全局单写者导入锁（带 TTL，进程被杀后自动过期）。

    产出的句柄提供 :meth:`LockHandle.extend`：长导入（超过 ``lock_ttl`` 900s 的
    大包完全可能）需要**续租**，否则锁会在任务跑到一半时自解，此时若恰好有第二个
    执行者（误起第二个 worker / 手工 `import_worker --once`），它就能拿到锁并同时
    往 SQLite 写——正是这把锁要防的事。
    """
    cfg = lim or limits()
    token = uuid.uuid4().hex
    if not _acquire(GLOBAL_LOCK_KEY, token, cfg.lock_ttl):
        raise ConflictError('已有导入任务在进行中，请稍后重试')
    try:
        yield LockHandle(GLOBAL_LOCK_KEY, token, cfg.lock_ttl)
    finally:
        _release(GLOBAL_LOCK_KEY, token)


class LockHandle:
    """已持有的锁：只允许续租，不暴露 token（避免被别的代码误释放）。"""

    def __init__(self, key: str, token: str, ttl: int) -> None:
        self._key = key
        self._token = token
        self._ttl = ttl

    def extend(self) -> None:
        """续租一次（比对 token 后再写，避免把别人的锁改成自己的 TTL）。"""
        try:
            if cache.get(self._key) == self._token:
                cache.set(self._key, self._token, self._ttl)
        except Exception:  # pragma: no cover - 缓存故障时交给原 TTL 自解
            logger.warning('归档锁续租失败，将由原 TTL 自动过期', exc_info=True)


def enforce_min_interval(user_id: int, lim: Limits | None = None) -> None:
    """同一用户两次导入的最小间隔。"""
    cfg = lim or limits()
    if cfg.import_min_interval <= 0:
        return
    key = INTERVAL_KEY.format(user_id=user_id)
    if not _acquire(key, uuid.uuid4().hex, cfg.import_min_interval):
        raise RateLimitedError('导入过于频繁，请稍后再试')
