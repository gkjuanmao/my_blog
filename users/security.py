"""账号安全公共动作：密码强度校验 + 改密后让旧会话失效。

为什么单独抽一个模块：超管「重置他人密码」（users/admin_api.py）与本人
「修改自己的密码」（users/api.py）必须走同一套口径——否则两个入口迟早
一个记得拉黑 refresh、另一个忘掉，出现「改了密码但旧令牌还能用」的漏洞。
"""
import logging
from typing import Any

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils import timezone
from ninja.errors import HttpError

logger = logging.getLogger(__name__)


def validate_password_or_400(password: str, user: Any) -> None:
    """用项目统一的 AUTH_PASSWORD_VALIDATORS 校验密码强度。

    Raises:
        HttpError: 400，把 Django 的中文校验提示原样拼回去，
            让前端能直接展示「密码太常见」这类具体原因。
    """
    try:
        validate_password(password, user)
    except ValidationError as exc:
        raise HttpError(400, '；'.join(exc.messages)) from None


def blacklist_refresh_tokens(user: Any) -> None:
    """把该用户未过期的 refresh token 全部拉黑。

    access token 的失效靠 ``password_changed_at``（见 users/authentication.py），
    这里补上 refresh 通道，避免旧 refresh 还能换出新 access。
    """
    try:
        from ninja_jwt.token_blacklist.models import BlacklistedToken, OutstandingToken
    except ImportError:  # pragma: no cover - 未装 token_blacklist app 时降级
        logger.warning('未启用 token_blacklist，跳过 refresh 拉黑')
        return
    for token in OutstandingToken.objects.filter(user=user, expires_at__gt=timezone.now()):
        BlacklistedToken.objects.get_or_create(token=token)


def change_user_password(user: Any, new_password: str) -> None:
    """写入新密码并让该用户此前签发的所有令牌失效。

    只负责「旧会话全部作废」，不负责签发新令牌：超管重置后对方应重新登录，
    而本人改密时可接着调 ``RefreshToken.for_user(user)`` 给自己发一对新令牌
    （必须在本函数之后调用——先发新令牌再拉黑会把自己的新 refresh 一起黑掉）。

    调用方需自行先用 ``validate_password_or_400`` 校验强度。
    """
    user.set_password(new_password)
    user.password_changed_at = timezone.now()
    user.save(update_fields=['password', 'password_changed_at'])
    blacklist_refresh_tokens(user)
