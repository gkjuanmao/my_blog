"""公开读接口的短 TTL 缓存。

用「版本号」实现整体失效：文章/分类/标签任一写操作都会 bump 版本号，
旧键自然不再被读取（无需按前缀删除，兼容 LocMemCache 与 Redis）。
缓存不可用时一律降级为直接查询，不影响可用性。
"""
from collections.abc import Callable
from typing import Any

from django.core.cache import cache

# 公开列表缓存 TTL（秒）；同时用于响应头 Cache-Control 的 max-age
PUBLIC_CACHE_TTL = 60
_VERSION_KEY = 'articles:public:version'


def _version() -> int:
    try:
        return int(cache.get(_VERSION_KEY, 1) or 1)
    except Exception:  # 缓存故障时退化为「每次都重建」
        return 1


def invalidate_public_cache() -> None:
    """文章/分类/标签发生写操作时调用，使公开列表缓存立即失效。"""
    try:
        cache.set(_VERSION_KEY, _version() + 1, None)
    except Exception:  # 缓存故障时无需失效（本就没有可用缓存）
        pass


def cached_public(key: str, build: Callable[[], Any]) -> Any:
    """读公开缓存；未命中则执行 ``build()`` 并写入。"""
    full_key = f'articles:public:{_version()}:{key}'
    try:
        hit = cache.get(full_key)
        if hit is not None:
            return hit
    except Exception:  # 缓存故障时降级为直接查询
        return build()
    value = build()
    try:
        cache.set(full_key, value, PUBLIC_CACHE_TTL)
    except Exception:
        pass
    return value
