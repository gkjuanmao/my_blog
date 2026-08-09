"""用户认证相关 API：登录、刷新令牌、当前用户信息。"""
from django.contrib.auth import authenticate
from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError
from ninja_jwt.tokens import RefreshToken, TokenError

from common.responses import success_response

from .authentication import JWTAuth
from .schemas import LoginIn, RefreshIn, UserOut

router = Router(tags=['认证'])

jwt_auth = JWTAuth()


@router.post('/login/', response=dict)
def obtain_token(request: HttpRequest, payload: LoginIn) -> dict:
    """登录：校验用户名密码，签发 access 与 refresh 令牌。"""
    user = authenticate(username=payload.username, password=payload.password)
    if user is None:
        raise HttpError(401, '用户名或密码错误')

    refresh = RefreshToken.for_user(user)  # type: ignore[misc]
    return success_response({
        'access': str(refresh.access_token),
        'refresh': str(refresh),
    })


@router.post('/token/refresh/', response=dict)
def refresh_token(request: HttpRequest, payload: RefreshIn) -> dict:
    """刷新令牌：校验 refresh token 并返回新的 access token。"""
    try:
        refresh = RefreshToken(payload.refresh)
    except TokenError:
        raise HttpError(401, 'refresh 令牌无效或已过期') from None

    return success_response({'access': str(refresh.access_token)})


@router.get('/me/', response=dict, auth=jwt_auth)
def get_me(request: HttpRequest) -> dict:
    """获取当前登录用户信息（需携带 Bearer Token）。"""
    user_out = UserOut.model_validate(request.auth)  # type: ignore[attr-defined]
    return success_response(user_out.model_dump())
