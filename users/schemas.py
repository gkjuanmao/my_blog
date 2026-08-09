"""用户相关数据结构：响应与请求 Schema。"""
from ninja import Field, ModelSchema, Schema

from .models import User


class UserOut(ModelSchema):
    """用户信息响应。"""

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'avatar', 'avatar_name', 'date_joined']


class LoginIn(Schema):
    """登录请求体。"""

    username: str = Field(..., min_length=1, description='用户名')
    password: str = Field(..., min_length=1, description='密码')


class TokenObtainPairOut(Schema):
    """登录成功返回 access 与 refresh 令牌。"""

    access: str
    refresh: str


class TokenRefreshOut(Schema):
    """刷新成功后仅返回新的 access 令牌。"""

    access: str


class RefreshIn(Schema):
    """令牌刷新请求体。"""

    refresh: str
