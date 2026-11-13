"""用户认证相关 API：登录、刷新令牌、当前用户信息。"""
import logging

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import update_last_login
from django.core.cache import cache
from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError
from ninja_jwt.tokens import RefreshToken, TokenError

from common.net import client_ip
from common.responses import success_response
from common.schemas import ApiResponse

from .authentication import JWTAuth
from .presence import touch_presence
from .schemas import (
    ChangePasswordIn,
    LoginIn,
    RefreshIn,
    TokenObtainPairOut,
    TokenRefreshOut,
    UserOut,
)
from .security import change_user_password, validate_password_or_400

router = Router(tags=['认证'])

logger = logging.getLogger(__name__)

jwt_auth = JWTAuth()

User = get_user_model()

# 登录失败限流：同一 客户端 IP + 用户名 在窗口内失败达到上限后返回 429
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 300

# 本人改密的「当前密码」校验失败限流：令牌泄漏后不能顺手爆破旧密码夺号
PASSWORD_CHANGE_MAX_ATTEMPTS = 5
PASSWORD_CHANGE_LOCKOUT_SECONDS = 300


def _login_throttle_key(request: HttpRequest, username: str) -> str:
    """登录失败计数的缓存键：按 IP + 小写用户名隔离。"""
    return f'login_failed:{client_ip(request)}:{username.strip().lower()}'


def _throttle_hits(key: str) -> int:
    """读失败计数。

    缓存后端（prod 为 Redis）不可用时不能把 /login/ 变成 500：这里 fail-open，
    因为限流是缓解手段而非鉴权本身。
    """
    try:
        return int(cache.get(key, 0) or 0)
    except Exception:  # pragma: no cover - 仅在缓存故障时触发
        logger.warning('登录限流缓存读取失败，本次跳过限流', exc_info=True)
        return 0


def _bump_throttle(key: str, seconds: int) -> None:
    """失败计数 +1；缓存故障只降级记日志，不把业务请求打成 500。"""
    try:
        cache.set(key, _throttle_hits(key) + 1, seconds)
    except Exception:  # pragma: no cover - 仅在缓存故障时触发
        logger.warning('限流计数写入失败，本次未计数', exc_info=True)


def _clear_throttle(key: str) -> None:
    """成功后清除计数。"""
    try:
        cache.delete(key)
    except Exception:  # pragma: no cover - 仅在缓存故障时触发
        logger.warning('限流缓存清除失败', exc_info=True)


@router.post('/login/', response=ApiResponse[TokenObtainPairOut])
def obtain_token(request: HttpRequest, payload: LoginIn) -> dict:
    """登录：校验用户名密码，签发 access 与 refresh 令牌。

    连续失败达到 ``LOGIN_MAX_ATTEMPTS`` 次后锁定 ``LOGIN_LOCKOUT_SECONDS`` 秒，
    期间一律返回 429（无论密码是否正确），用于缓解暴力破解。
    """
    key = _login_throttle_key(request, payload.username)
    if _throttle_hits(key) >= LOGIN_MAX_ATTEMPTS:
        raise HttpError(429, '登录失败次数过多，请 5 分钟后再试')

    user = authenticate(username=payload.username, password=payload.password)
    if user is None:
        _bump_throttle(key, LOGIN_LOCKOUT_SECONDS)
        raise HttpError(401, '用户名或密码错误')

    # 登录成功清除失败计数
    _clear_throttle(key)
    # 登录是最明确的在线信号：跳过节流直接写 last_seen_at，并补上 last_login
    # （AbstractUser.last_login 只在 django.contrib.auth.login() 里更新，走 JWT 不会自动写）
    touch_presence(user, force=True)
    update_last_login(type(user), user)
    refresh = RefreshToken.for_user(user)  # type: ignore[misc]
    return success_response({
        'access': str(refresh.access_token),
        'refresh': str(refresh),
    })


@router.post('/token/refresh/', response=ApiResponse[TokenRefreshOut])
def refresh_token(request: HttpRequest, payload: RefreshIn) -> dict:
    """刷新令牌：校验 refresh token，签发新 access 并轮换 refresh。

    启用 ``BLACKLIST_AFTER_ROTATION`` 时，旧 refresh token 会被加入黑名单，
    无法再次使用（需已安装 ``ninja_jwt.token_blacklist``）。
    """
    try:
        refresh = RefreshToken(payload.refresh)
    except TokenError:
        raise HttpError(401, 'refresh 令牌无效或已过期') from None

    user = User.objects.filter(pk=refresh['user_id']).first()
    if user is None:
        raise HttpError(401, '用户不存在')
    # 与 JWTAuth 同一口径：停用的账号不许再换新令牌
    if not user.is_active:
        raise HttpError(401, '账号已停用')

    new_refresh = RefreshToken.for_user(user)  # type: ignore[misc]
    if settings.SIMPLE_JWT.get('BLACKLIST_AFTER_ROTATION') and hasattr(refresh, 'blacklist'):
        refresh.blacklist()

    return success_response({
        'access': str(new_refresh.access_token),
        'refresh': str(new_refresh),
    })


@router.get('/me/', response=ApiResponse[UserOut], auth=jwt_auth)
def get_me(request: HttpRequest) -> dict:
    """获取当前登录用户信息（需携带 Bearer Token）。"""
    user_out = UserOut.model_validate(request.auth)  # type: ignore[attr-defined]
    return success_response(user_out.model_dump())


@router.post('/password/change/', response=ApiResponse[TokenObtainPairOut], auth=jwt_auth)
def change_own_password(request: HttpRequest, payload: ChangePasswordIn) -> dict:
    """修改自己的密码（需同时提供当前密码）。

    与超管「重置他人密码」的两点差别：

    1. **必须验旧密码**：否则拿到 access token 的人可以直接改密把账号占走，
       把「令牌泄漏」升级成「账号被夺」。失败次数同样限流，防爆破旧密码。
    2. **返回一对新令牌**：本人当前会话不断，其他设备因 ``password_changed_at``
       与 refresh 拉黑而全部掉线。注意顺序——先作废旧会话再签新令牌，
       反过来会把自己的新 refresh 一起拉黑。

    所有密码强度规则复用项目 ``AUTH_PASSWORD_VALIDATORS``，与超管端一致。
    """
    user = request.auth  # type: ignore[attr-defined]
    key = f'password_change_failed:{user.pk}'

    if _throttle_hits(key) >= PASSWORD_CHANGE_MAX_ATTEMPTS:
        raise HttpError(429, '当前密码错误次数过多，请 5 分钟后再试')
    if not user.check_password(payload.old_password):
        _bump_throttle(key, PASSWORD_CHANGE_LOCKOUT_SECONDS)
        raise HttpError(400, '当前密码不正确')
    if payload.old_password == payload.new_password:
        raise HttpError(400, '新密码不能与当前密码相同')

    validate_password_or_400(payload.new_password, user)
    change_user_password(user, payload.new_password)
    _clear_throttle(key)

    refresh = RefreshToken.for_user(user)  # type: ignore[misc]
    return success_response(
        {'access': str(refresh.access_token), 'refresh': str(refresh)},
        message='密码已更新，其他设备的登录状态已失效',
    )
