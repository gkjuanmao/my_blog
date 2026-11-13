"""用户管理 API（仅超级管理员）：列表 / 创建 / 更新 / 重置密码 / 删除。

为什么单独一个模块而不是塞进 ``users/api.py``：那边是公开的登录/刷新/me，
这里全是超管端点，鉴权口径与风险等级完全不同，混在一起最容易在改认证时
把管理端点一起放开。
"""
import logging
import re

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Count, Q, QuerySet
from django.http import HttpRequest
from django.utils import timezone
from ninja import Query, Router, Status
from ninja.errors import HttpError

from common.responses import success_response
from common.schemas import ApiResponse, PageData

from .authentication import SuperUserJWTAuth
from .presence import is_online
from .schemas import AdminUserOut, ResetPasswordIn, UserCreateIn, UserUpdateIn

logger = logging.getLogger(__name__)

router = Router(tags=['用户管理'])

superuser_auth = SuperUserJWTAuth()

User = get_user_model()

# 排序白名单：与 Django 字段名一致，非法值返回 400（对齐文章列表的口径）
ADMIN_USER_ORDERING_FIELDS = frozenset(
    {'username', 'date_joined', 'last_login', 'last_seen_at', 'is_active'}
)

# 与 Django UnicodeUsernameValidator 对齐：字母/数字/汉字 + @ . + - _
USERNAME_PATTERN = re.compile(r'^[\w.@+-]+$')


def _get_user_or_404(user_id: int):
    """按主键取用户，不存在时抛 404（而不是让 ninja 返回 500）。"""
    try:
        return User.objects.annotate(article_count=Count('article')).get(pk=user_id)
    except User.DoesNotExist:
        raise HttpError(404, '用户不存在') from None


def _validate_password_strength(password: str, user) -> None:
    """用项目统一的 AUTH_PASSWORD_VALIDATORS 校验密码强度。

    Raises:
        HttpError: 400，把 Django 的中文校验提示原样拼回去，
            让前端能直接展示「密码太常见」这类具体原因。
    """
    try:
        validate_password(password, user)
    except ValidationError as exc:
        raise HttpError(400, '；'.join(exc.messages)) from None


def _validate_email_or_400(email: str) -> str:
    """校验邮箱格式，空字符串表示不填。"""
    email = email.strip()
    if not email:
        return ''
    try:
        validate_email(email)
    except ValidationError:
        raise HttpError(400, '邮箱格式不正确') from None
    return email


def _to_out(user) -> AdminUserOut:
    """模型实例 → 响应结构，顺带算好在线状态。

    ``online`` 由服务端判定：前端时钟不可信，且窗口是后端配置项；
    ``avatar_url`` 返回相对路径（与文章封面同一口径，见 tests/test_media_url_relative.py）。
    """
    return AdminUserOut(
        id=user.pk,
        username=user.username,
        email=user.email,
        is_active=user.is_active,
        is_staff=user.is_staff,
        is_superuser=user.is_superuser,
        avatar_url=user.avatar.url if user.avatar else None,
        date_joined=user.date_joined,
        last_login=user.last_login,
        last_seen_at=user.last_seen_at,
        online=is_online(user.last_seen_at),
        article_count=getattr(user, 'article_count', 0),
    )


def _active_superuser_count(exclude_pk: int) -> int:
    """除指定用户外，还有几个启用状态的超管。"""
    return User.objects.filter(is_superuser=True, is_active=True).exclude(pk=exclude_pk).count()


def _blacklist_refresh_tokens(user) -> None:
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


def _user_queryset() -> QuerySet:
    """列表基础查询：带文章数注解，避免每行再查一次。"""
    return User.objects.annotate(article_count=Count('article'))


@router.get('/users/', response=ApiResponse[PageData[AdminUserOut]], auth=superuser_auth)
def list_users(
    request: HttpRequest,
    page: int = Query(1, ge=1, description='页码'),
    page_size: int = Query(10, ge=1, le=100, description='每页数量'),
    keyword: str = Query('', max_length=150, description='用户名/邮箱关键词'),
    is_active: bool | None = Query(None, description='按启用状态过滤'),
    is_staff: bool | None = Query(None, description='按后台权限过滤'),
    ordering: str = Query('', description='排序字段：last_seen_at / -last_seen_at 等'),
) -> dict:
    """用户列表：含在线状态与文章数，供后台台账展示。"""
    qs = _user_queryset()
    if keyword:
        qs = qs.filter(Q(username__icontains=keyword) | Q(email__icontains=keyword))
    if is_active is not None:
        qs = qs.filter(is_active=is_active)
    if is_staff is not None:
        qs = qs.filter(is_staff=is_staff)
    if ordering:
        field = ordering.lstrip('-')
        if field not in ADMIN_USER_ORDERING_FIELDS:
            raise HttpError(400, '不支持的排序字段')
        # 追加 -id 作次要键，避免排序值相同（如都没活跃过）时翻页重复/遗漏
        qs = qs.order_by(ordering, '-id')
    else:
        qs = qs.order_by('-is_superuser', '-date_joined', '-id')

    total = qs.count()
    start = (page - 1) * page_size
    items = [_to_out(user).model_dump() for user in qs[start:start + page_size]]
    return success_response({'items': items, 'total': total, 'page': page, 'page_size': page_size})


@router.get('/users/{int:user_id}/', response=ApiResponse[AdminUserOut], auth=superuser_auth)
def get_user(request: HttpRequest, user_id: int) -> dict:
    """单个用户详情。"""
    return success_response(_to_out(_get_user_or_404(user_id)).model_dump())


@router.post('/users/', response={201: ApiResponse[AdminUserOut]}, auth=superuser_auth)
def create_user(request: HttpRequest, payload: UserCreateIn) -> Status:
    """创建用户：用户名/秒级唯一性 + 密码强度与邮箱格式都在这里把关。"""
    username = payload.username.strip()
    if not USERNAME_PATTERN.match(username):
        raise HttpError(400, '用户名只能包含字母、数字和 @ . + - _ 字符')
    # 用 iexact 挡近似重名（DB 唯一约束本身区分大小写），避免 admin/Admin 两个号并存
    if User.objects.filter(username__iexact=username).exists():
        raise HttpError(409, '用户名已存在')

    email = _validate_email_or_400(payload.email)
    user = User(
        username=username,
        email=email,
        # 超管必须同时是 staff，否则进不了 Django admin 却又能管理账号，语义混乱
        is_staff=payload.is_staff or payload.is_superuser,
        is_superuser=payload.is_superuser,
        is_active=payload.is_active,
    )
    _validate_password_strength(payload.password, user)
    user.set_password(payload.password)
    user.save()

    return Status(201, success_response(_to_out(_get_user_or_404(user.pk)).model_dump(), code=201))


@router.put('/users/{int:user_id}/', response=ApiResponse[AdminUserOut], auth=superuser_auth)
def update_user(request: HttpRequest, user_id: int, payload: UserUpdateIn) -> dict:
    """更新用户资料与角色（不含密码）。

    两道自锁保护：不能改自己的角色/启用状态（改了自己就进不来），
    也不能把最后一个启用中的超管降级。
    """
    user = _get_user_or_404(user_id)
    current_user = request.auth  # type: ignore[attr-defined]

    role_changed = (payload.is_staff != user.is_staff) or (
        payload.is_superuser != user.is_superuser
    ) or (payload.is_active != user.is_active)
    if user.pk == current_user.pk and role_changed:
        raise HttpError(400, '不能修改自己的角色或启用状态')

    if user.is_superuser and not payload.is_superuser and _active_superuser_count(user.pk) == 0:
        raise HttpError(400, '至少保留一个启用状态的超级管理员')
    if user.is_superuser and not payload.is_active and _active_superuser_count(user.pk) == 0:
        raise HttpError(400, '至少保留一个启用状态的超级管理员')

    user.email = _validate_email_or_400(payload.email)
    user.is_superuser = payload.is_superuser
    user.is_staff = payload.is_staff or payload.is_superuser
    user.is_active = payload.is_active
    user.save(update_fields=['email', 'is_staff', 'is_superuser', 'is_active'])

    return success_response(_to_out(_get_user_or_404(user.pk)).model_dump(), message='用户已更新')


@router.post(
    '/users/{int:user_id}/reset-password/',
    response=ApiResponse[dict],
    auth=superuser_auth,
)
def reset_user_password(request: HttpRequest, user_id: int, payload: ResetPasswordIn) -> dict:
    """重置密码（超管手输新密码）。

    同时做两件事让旧会话立刻失效：
    写入 ``password_changed_at``（JWTAuth 比对令牌 iat）+ 拉黑该用户全部 refresh。
    """
    user = _get_user_or_404(user_id)
    _validate_password_strength(payload.password, user)

    user.set_password(payload.password)
    user.password_changed_at = timezone.now()
    user.save(update_fields=['password', 'password_changed_at'])
    _blacklist_refresh_tokens(user)

    return success_response(
        {'id': user.pk, 'username': user.username},
        message='密码已重置，该用户需重新登录',
    )


@router.delete('/users/{int:user_id}/', response=ApiResponse[dict], auth=superuser_auth)
def delete_user(
    request: HttpRequest,
    user_id: int,
    reassign_to: int | None = Query(None, description='把该用户的文章转移给指定用户 id'),
    force: bool = Query(False, description='强制删除并级联删除其文章'),
) -> dict:
    """删除用户。

    默认**拒绝**删除仍有文章的用户（``Article.author`` 是 CASCADE，直接删会连带
    删掉文章），必须显式选择「转移给他人」或「强制级联删除」，避免一次误点
    带走整个作者的全部稿件。
    """
    user = _get_user_or_404(user_id)
    current_user = request.auth  # type: ignore[attr-defined]

    if user.pk == current_user.pk:
        raise HttpError(400, '不能删除当前登录账号')
    if user.is_superuser and _active_superuser_count(user.pk) == 0:
        raise HttpError(400, '至少保留一个启用状态的超级管理员')

    article_count = getattr(user, 'article_count', 0)
    reassigned = 0
    if article_count:
        if reassign_to is not None:
            if reassign_to == user.pk:
                raise HttpError(400, '不能把文章转移给被删除的用户')
            target = _get_user_or_404(reassign_to)
            # 局部导入：articles.api 依赖 users.authentication，模块级导入会成环
            from articles.models import Article

            with transaction.atomic():
                # 显式写 updated_at：auto_now 只在 save() 时生效，update() 不会自动改
                reassigned = Article.objects.filter(author=user).update(
                    author=target, updated_at=timezone.now()
                )
                user.delete()
        elif force:
            # 交给 CASCADE；articles/signals.py 的 post_delete 会清理封面/附件文件
            user.delete()
        else:
            raise HttpError(
                409,
                f'该用户还有 {article_count} 篇文章，请先转移文章或选择强制删除',
            )
    else:
        user.delete()

    return success_response(
        {'username': user.username, 'reassigned_articles': reassigned},
        message='用户已删除',
    )
