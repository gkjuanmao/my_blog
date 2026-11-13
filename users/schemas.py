"""用户相关数据结构：响应与请求 Schema。"""
from datetime import datetime

from ninja import Field, ModelSchema, Schema

from .models import User


class UserOut(ModelSchema):
    """用户信息响应。

    带 ``is_staff`` / ``is_superuser``：前端后台需要按权限渲染导航
    （用户管理只对超管开放），此前硬编码成「admin 管理员」。
    """

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'email',
            'avatar',
            'avatar_name',
            'date_joined',
            'is_staff',
            'is_superuser',
        ]


class AdminUserOut(Schema):
    """用户管理列表/详情的行数据。

    ``online`` 由服务端按 ``USER_ONLINE_WINDOW_SECONDS`` 算好一起返回，
    避免前后端时钟不一致导致「在线」判断飘移；``last_seen_at`` 供前端展示
    「x 分钟前」这类相对时间。
    """

    id: int
    username: str
    email: str
    is_active: bool
    is_staff: bool
    is_superuser: bool
    avatar_url: str | None = None
    date_joined: datetime
    last_login: datetime | None = None
    last_seen_at: datetime | None = None
    online: bool = False
    article_count: int = 0


class UserCreateIn(Schema):
    """创建用户请求体（本项目无公开注册，账号一律由超管创建）。"""

    username: str = Field(..., min_length=3, max_length=150, description='用户名')
    password: str = Field(..., min_length=8, max_length=128, description='初始密码')
    email: str = Field('', max_length=254, description='邮箱，可留空')
    is_staff: bool = Field(False, description='是否可进后台管理稿件')
    is_superuser: bool = Field(False, description='是否超级管理员（会自动带上 staff）')
    is_active: bool = Field(True, description='是否启用')


class UserUpdateIn(Schema):
    """更新用户请求体：不含密码，改密走 reset-password 端点。"""

    email: str = Field('', max_length=254, description='邮箱，可留空')
    is_staff: bool = Field(False, description='是否可进后台管理稿件')
    is_superuser: bool = Field(False, description='是否超级管理员（会自动带上 staff）')
    is_active: bool = Field(True, description='是否启用')


class ResetPasswordIn(Schema):
    """重置密码请求体：由超管手动输入新密码。"""

    password: str = Field(..., min_length=8, max_length=128, description='新密码（至少 8 位）')


class ChangePasswordIn(Schema):
    """本人修改密码请求体：必须提供当前密码。

    为什么强制要旧密码：否则任何拿到 access token 的人都能直接改密并永久占据账号，
    相当于把「令牌泄漏」升级成「账号被夺」。
    """

    old_password: str = Field(..., min_length=1, max_length=128, description='当前密码')
    new_password: str = Field(..., min_length=8, max_length=128, description='新密码（至少 8 位）')


class LoginIn(Schema):
    """登录请求体。"""

    username: str = Field(..., min_length=1, description='用户名')
    password: str = Field(..., min_length=1, description='密码')


class TokenObtainPairOut(Schema):
    """登录成功返回 access 与 refresh 令牌。"""

    access: str
    refresh: str


class TokenRefreshOut(Schema):
    """刷新成功返回新的 access 与轮换后的 refresh 令牌。"""

    access: str
    refresh: str


class RefreshIn(Schema):
    """令牌刷新请求体。"""

    refresh: str
