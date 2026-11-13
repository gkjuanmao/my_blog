"""自定义 JWT 认证类：校验请求头中的 Bearer Token。"""
from datetime import datetime
from typing import Any

from django.contrib.auth import get_user_model
from ninja.errors import HttpError
from ninja.security import HttpBearer
from ninja_jwt.tokens import AccessToken, TokenError

from .presence import touch_presence

User = get_user_model()


def _as_timestamp(value: Any) -> int | None:
    """把令牌里的时间声明统一成秒级时间戳。

    令牌刚构造时 ``iat`` 是 datetime（内存对象），从字符串解析时则是 int，
    两种形态都要能比较。
    """
    if isinstance(value, datetime):
        return int(value.timestamp())
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _ensure_token_not_revoked(user: Any, access_token: AccessToken) -> None:
    """改密后作废旧令牌：令牌签发时间早于用户最近改密时间即拒绝。

    本项目的 django-ninja-jwt 不支持 SimpleJWT 的 ``CHECK_REVOKE_TOKEN``，
    而 access token 有效期 2 小时；若不做这一步，超管重置密码后旧令牌仍能
    继续操作，等于改密没生效。用严格小于比较：改密同一秒内新签发的令牌仍然有效。

    Raises:
        HttpError: 401，提示密码已变更需重新登录。
    """
    changed_at = getattr(user, 'password_changed_at', None)
    if not changed_at:
        return
    issued_at = _as_timestamp(access_token.get('iat'))
    if issued_at is None:
        return
    if issued_at < int(changed_at.timestamp()):
        raise HttpError(401, '密码已变更，请重新登录')


class JWTAuth(HttpBearer):
    """基于 django-ninja-jwt 的自定义 Bearer 认证。

    校验 Authorization: Bearer <access token>，并返回对应用户对象。
    令牌无效、过期、改密后失效或用户不存在时抛出 401。
    """

    def authenticate(self, request, token: str):
        try:
            access_token = AccessToken(token)
            user_id = access_token['user_id']
        except TokenError:
            raise HttpError(401, '令牌无效或已过期') from None

        # 每次请求都同步查库取用户对象（而非只信任令牌里的 user_id）：
        # 这样用户被停用/删除/降权后能立即失效，是安全与一次 DB 往返之间的取舍。
        # 若将来要缓存，必须处理失效（如用户删除/改权限时清缓存），否则会放行已停用账号。
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            raise HttpError(401, '用户不存在') from None

        # 停用要真的生效：否则超管在后台点了「停用」，对方手里的令牌还能再用满 2 小时
        if not user.is_active:
            raise HttpError(401, '账号已停用')

        _ensure_token_not_revoked(user, access_token)
        # 在线状态在这里埋点：这是所有鉴权请求的必经路径。
        # 内部按 USER_PRESENCE_THROTTLE_SECONDS 节流，且任何失败都不会影响本请求。
        touch_presence(user)
        return user


class StaffJWTAuth(JWTAuth):
    """在 JWT 校验基础上要求 is_staff / is_superuser。

    用于归档导入导出等高风险端点：普通登录用户（只要在 admin 里被建过账号）
    不应能导出全部草稿或执行破坏性导入。
    """

    def authenticate(self, request, token: str):
        user = super().authenticate(request, token)
        if user is not None and not (user.is_staff or user.is_superuser):
            raise HttpError(403, '需要管理员权限')
        return user


class SuperUserJWTAuth(JWTAuth):
    """在 JWT 校验基础上要求 is_superuser。

    用于用户管理这类「能动别人账号」的端点：staff（能写文章）不应有权创建、
    删除账号或重置他人密码，否则一次账号泄漏就能横向提权。
    """

    def authenticate(self, request, token: str):
        user = super().authenticate(request, token)
        if user is not None and not user.is_superuser:
            raise HttpError(403, '需要超级管理员权限')
        return user
