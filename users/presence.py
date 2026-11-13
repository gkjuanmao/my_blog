"""用户在线状态：把「最近活跃时间」写进数据库，缓存只用于节流写库。

为什么事实来源是数据库而不是缓存 TTL：
``CACHES`` 在 dev/测试是 LocMemCache（每进程一份），prod 未配 REDIS_URL 时同样回落
LocMemCache，而 gunicorn 是 3 workers。用缓存存 presence 会让「在线」在 worker 间
各说各话；把缓存降级成节流闸门后，最坏情况只是活跃度晚记一个窗口，不会判错。
"""
import logging
from datetime import datetime
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)


def _throttle_seconds() -> int:
    """节流窗口（秒）；非正值表示不节流。"""
    return int(getattr(settings, 'USER_PRESENCE_THROTTLE_SECONDS', 60))


def _recently_written(user: Any, now: datetime, throttle: int) -> bool:
    """缓存不可用时的降级判断：用已加载的 ``last_seen_at`` 兜底节流。

    鉴权流程里的 user 是刚查出来的，字段值可信，因此这里不需要额外查询。
    """
    last_seen = getattr(user, 'last_seen_at', None)
    return bool(last_seen and (now - last_seen).total_seconds() < throttle)


def touch_presence(user: Any, *, force: bool = False) -> bool:
    """记录用户最近活跃时间，返回本次是否真的写库。

    Args:
        user: 已通过令牌校验的用户对象。
        force: 跳过节流立即写库（登录成功时用，登录本身就该算活跃）。

    Returns:
        是否执行了写库；写库失败或命中节流都返回 False。

    Raises:
        无：活跃度属于展示数据，任何异常都在内部吞掉并降级，
        绝不能因为写活跃时间把业务请求打成 500。
    """
    pk = getattr(user, 'pk', None)
    if not pk:
        return False

    now = timezone.now()
    throttle = _throttle_seconds()

    if not force and throttle > 0:
        try:
            # cache.add 是原子的「不存在才写」：键已存在返回 False，
            # 天然去重，不用先 get 再 set（那样并发下会重复写库）
            if not cache.add(f'user_presence:{pk}', 1, throttle):
                return False
        except Exception:  # pragma: no cover - 仅在缓存故障时触发
            logger.debug('在线状态节流写入失败，降级为按 last_seen_at 判断', exc_info=True)
            if _recently_written(user, now, throttle):
                return False

    try:
        # 单字段 update：不走 save()，不会把并发修改的其他字段用旧快照写回，
        # 也不会误触发 auto_now 字段
        user.__class__.objects.filter(pk=pk).update(last_seen_at=now)
    except Exception:  # pragma: no cover - 仅在数据库不可写时触发
        logger.debug('更新用户活跃时间失败', exc_info=True)
        return False

    user.last_seen_at = now
    return True


def is_online(last_seen_at: datetime | None, *, now: datetime | None = None) -> bool:
    """按在线窗口判断是否在线。

    Args:
        last_seen_at: 用户最近活跃时间，None 表示从未活跃过。
        now: 参照时间，默认取当前时间（测试可注入固定值）。

    Returns:
        ``now - last_seen_at <= USER_ONLINE_WINDOW_SECONDS`` 时为 True。
    """
    if last_seen_at is None:
        return False
    window = int(getattr(settings, 'USER_ONLINE_WINDOW_SECONDS', 900))
    current = now or timezone.now()
    return (current - last_seen_at).total_seconds() <= window
