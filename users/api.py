"""用户认证相关 API：登录、刷新令牌、当前用户信息。"""
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.core.cache import cache
from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError
from ninja_jwt.tokens import RefreshToken, TokenError

from common.responses import success_response
from common.schemas import ApiResponse

from .authentication import JWTAuth
from .schemas import LoginIn, RefreshIn, TokenObtainPairOut, TokenRefreshOut, UserOut

router = Router(tags=['认证'])

jwt_auth = JWTAuth()

User = get_user_model()

# 登录失败限流：同一 客户端 IP + 用户名 在窗口内失败达到上限后返回 429
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 300


def _client_ip(request: HttpRequest) -> str:
    """取真实客户端 IP。

    nginx 以 ``$proxy_add_x_forwarded_for`` 追加真实来源，因此取 X-Forwarded-For
    的**最后一段**（由我们的 nginx 写入）；取第一段会被客户端伪造。
    """
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[-1].strip()
    return request.META.get('REMOTE_ADDR', '')


def _login_throttle_key(request: HttpRequest, username: str) -> str:
    """登录失败计数的缓存键：按 IP + 小写用户名隔离。"""
    return f'login_failed:{_client_ip(request)}:{username.strip().lower()}'


@router.post('/login/', response=ApiResponse[TokenObtainPairOut])
def obtain_token(request: HttpRequest, payload: LoginIn) -> dict:
    """登录：校验用户名密码，签发 access 与 refresh 令牌。

    连续失败达到 ``LOGIN_MAX_ATTEMPTS`` 次后锁定 ``LOGIN_LOCKOUT_SECONDS`` 秒，
    期间一律返回 429（无论密码是否正确），用于缓解暴力破解。
    """
    key = _login_throttle_key(request, payload.username)
    if cache.get(key, 0) >= LOGIN_MAX_ATTEMPTS:
        raise HttpError(429, '登录失败次数过多，请 5 分钟后再试')

    user = authenticate(username=payload.username, password=payload.password)
    if user is None:
        cache.set(key, cache.get(key, 0) + 1, LOGIN_LOCKOUT_SECONDS)
        raise HttpError(401, '用户名或密码错误')

    # 登录成功清除失败计数
    cache.delete(key)
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
