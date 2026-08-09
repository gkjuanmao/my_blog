"""自定义 JWT 认证类：校验请求头中的 Bearer Token。"""
from django.contrib.auth import get_user_model
from ninja.errors import HttpError
from ninja.security import HttpBearer
from ninja_jwt.tokens import AccessToken, TokenError

User = get_user_model()


class JWTAuth(HttpBearer):
    """基于 django-ninja-jwt 的自定义 Bearer 认证。

    校验 Authorization: Bearer <access token>，并返回对应用户对象。
    令牌无效、过期或用户不存在时抛出 401。
    """

    def authenticate(self, request, token: str):
        try:
            access_token = AccessToken(token)
            user_id = access_token['user_id']
        except TokenError:
            raise HttpError(401, '令牌无效或已过期') from None

        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            raise HttpError(401, '用户不存在') from None

        return user
