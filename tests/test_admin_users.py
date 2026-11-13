"""用户管理 API 测试：权限矩阵、列表、创建、更新、重置密码、删除语义。

口径：
- 一律要求 ``is_superuser``（staff 也不行），这是「能动别人账号」的最低门槛；
- 重置密码必须让旧 access token 立即失效（本项目 JWT 无 CHECK_REVOKE_TOKEN，靠
  ``password_changed_at`` 与令牌 iat 比对实现）；
- 删除有文章的用户默认 409，必须显式选择转移或强制级联删除。
"""
from datetime import timedelta

import pytest
from django.contrib.auth import authenticate
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from ninja_jwt.tokens import RefreshToken

from users.models import User

BASE = '/api/v1/admin/users/'


@pytest.fixture
def superuser(db) -> User:
    """超级管理员：用户管理端点的唯一合法身份。"""
    return User.objects.create_superuser(
        username='root', password='rootpass123', email='root@example.com'
    )


@pytest.fixture
def make_article(article_factory, jpeg_factory):
    """建一篇属于指定用户的文章（封面必须是真实 JPEG 字节）。"""

    def _make(user, slug: str):
        return article_factory(user, slug=slug, cover_bytes=jpeg_factory())

    return _make


@pytest.fixture
def root_header(superuser) -> dict:
    refresh = RefreshToken.for_user(superuser)  # type: ignore[misc]
    return {'HTTP_AUTHORIZATION': f'Bearer {refresh.access_token}'}


def _create_payload(**overrides) -> dict:
    payload = {
        'username': 'newuser',
        'password': 'Str0ng-pass-2026',
        'email': 'new@example.com',
        'is_staff': False,
        'is_superuser': False,
        'is_active': True,
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
class TestUserAdminPermissions:
    """USER-001 权限矩阵：匿名 401 / 普通用户 403 / staff 403 / 超管放行。"""

    def test_user_001_anonymous_401(self, api_client):
        assert api_client.get(BASE).status_code == 401

    def test_user_002_plain_user_403(self, api_client, plain_header):
        assert api_client.get(BASE, **plain_header).status_code == 403

    def test_user_003_staff_403(self, api_client, staff_header):
        """staff 能管文章，但不应能管账号（防横向提权）。"""
        response = api_client.get(BASE, **staff_header)

        assert response.status_code == 403
        assert '超级管理员' in response.json()['message']

    def test_user_004_superuser_200(self, api_client, root_header):
        assert api_client.get(BASE, **root_header).status_code == 200


@pytest.mark.django_db
class TestUserList:
    """USER-010 列表：分页、过滤、排序白名单与在线状态。"""

    def test_user_010_list_shape(self, api_client, root_header, superuser):
        response = api_client.get(BASE, **root_header)

        assert response.status_code == 200
        data = response.json()['data']
        assert data['total'] == 1
        assert data['page'] == 1 and data['page_size'] == 10
        row = data['items'][0]
        assert row['username'] == 'root'
        assert row['is_superuser'] is True
        # 列表请求本身要经鉴权，于是「正在看列表的自己」就是在线状态
        assert row['online'] is True
        assert row['article_count'] == 0
        assert 'password' not in row

    def test_user_011_online_uses_window(self, api_client, root_header, db):
        """在线判定：900 秒窗口内为在线，超出即离线，由服务端算好返回。

        只用「旁观用户」验证窗口，不动调用者——调用者每次请求都会被刷新成在线。
        """
        recent = User.objects.create_user(
            username='recent',
            password='recentpass123',
            last_seen_at=timezone.now() - timedelta(seconds=120),
        )
        stale = User.objects.create_user(
            username='stale',
            password='stalepass123',
            last_seen_at=timezone.now() - timedelta(seconds=901),
        )
        never = User.objects.create_user(username='never', password='neverpass123')

        response = api_client.get(BASE, **root_header)

        rows = {row['username']: row for row in response.json()['data']['items']}
        assert rows[recent.username]['online'] is True
        assert rows[stale.username]['online'] is False
        assert rows[never.username]['online'] is False

    def test_user_012_keyword_filter(self, api_client, root_header, user):
        response = api_client.get(BASE, {'keyword': 'testuser'}, **root_header)

        data = response.json()['data']
        assert data['total'] == 1
        assert data['items'][0]['username'] == 'testuser'

    def test_user_013_is_active_filter(self, api_client, root_header, superuser):
        User.objects.create_user(username='frozen', password='frozenpass123', is_active=False)

        response = api_client.get(BASE, {'is_active': 'false'}, **root_header)

        data = response.json()['data']
        assert data['total'] == 1
        assert data['items'][0]['username'] == 'frozen'

    def test_user_014_ordering_whitelist(self, api_client, root_header):
        ok = api_client.get(BASE, {'ordering': '-last_seen_at'}, **root_header)
        assert ok.status_code == 200

        bad = api_client.get(BASE, {'ordering': 'password'}, **root_header)
        assert bad.status_code == 400
        assert '不支持的排序字段' in bad.json()['message']

    def test_user_015_article_count(self, api_client, root_header, user, make_article):
        make_article(user, 'u-015')

        response = api_client.get(BASE, {'keyword': 'testuser'}, **root_header)

        assert response.json()['data']['items'][0]['article_count'] == 1


@pytest.mark.django_db
class TestUserCreate:
    """USER-020 创建用户。"""

    def test_user_020_create_ok(self, api_client, root_header):
        response = api_client.post(
            BASE, _create_payload(), content_type='application/json', **root_header
        )

        assert response.status_code == 201
        body = response.json()
        assert body['code'] == 201
        assert body['data']['username'] == 'newuser'
        # 密码必须真的可用，而不是只写进了字段
        assert authenticate(username='newuser', password='Str0ng-pass-2026') is not None

    def test_user_021_duplicate_username_409(self, api_client, root_header, user):
        """大小写不同也算重名，避免 admin / Admin 两个号并存。"""
        response = api_client.post(
            BASE,
            _create_payload(username='TestUser'),
            content_type='application/json',
            **root_header,
        )

        assert response.status_code == 409
        assert '用户名已存在' in response.json()['message']

    def test_user_022_weak_password_400(self, api_client, root_header):
        response = api_client.post(
            BASE,
            _create_payload(password='12345678'),
            content_type='application/json',
            **root_header,
        )

        assert response.status_code == 400

    def test_user_023_invalid_username_400(self, api_client, root_header):
        response = api_client.post(
            BASE,
            _create_payload(username='bad name!'),
            content_type='application/json',
            **root_header,
        )

        assert response.status_code == 400
        assert '用户名只能包含' in response.json()['message']

    def test_user_024_invalid_email_400(self, api_client, root_header):
        response = api_client.post(
            BASE,
            _create_payload(email='not-an-email'),
            content_type='application/json',
            **root_header,
        )

        assert response.status_code == 400
        assert '邮箱格式不正确' in response.json()['message']

    def test_user_025_superuser_implies_staff(self, api_client, root_header):
        response = api_client.post(
            BASE,
            _create_payload(username='boss', is_superuser=True, is_staff=False),
            content_type='application/json',
            **root_header,
        )

        assert response.status_code == 201
        assert response.json()['data']['is_staff'] is True


@pytest.mark.django_db
class TestUserUpdate:
    """USER-030 更新资料与角色的自锁保护。"""

    def test_user_030_update_email_and_role(self, api_client, root_header, user):
        response = api_client.put(
            f'{BASE}{user.pk}/',
            {
                'email': 'changed@example.com',
                'is_staff': True,
                'is_superuser': False,
                'is_active': True,
            },
            content_type='application/json',
            **root_header,
        )

        assert response.status_code == 200
        user.refresh_from_db()
        assert user.email == 'changed@example.com'

    def test_user_031_cannot_change_own_role(self, api_client, root_header, superuser):
        response = api_client.put(
            f'{BASE}{superuser.pk}/',
            {
                'email': superuser.email,
                'is_staff': True,
                'is_superuser': False,
                'is_active': True,
            },
            content_type='application/json',
            **root_header,
        )

        assert response.status_code == 400
        assert '不能修改自己' in response.json()['message']

    def test_user_032_can_update_own_email_keeping_role(self, api_client, root_header, superuser):
        """自锁保护只拦「改自己的角色/状态」，改自己的邮箱应当放行。"""
        response = api_client.put(
            f'{BASE}{superuser.pk}/',
            {
                'email': 'root-new@example.com',
                'is_staff': True,
                'is_superuser': True,
                'is_active': True,
            },
            content_type='application/json',
            **root_header,
        )

        assert response.status_code == 200
        superuser.refresh_from_db()
        assert superuser.email == 'root-new@example.com'

    def test_user_033_deactivate_kills_existing_token(self, api_client, root_header, user):
        """停用必须立刻生效：JWTAuth 里检查 is_active，旧令牌下一次请求就 401。"""
        refresh = RefreshToken.for_user(user)  # type: ignore[misc]
        header = {'HTTP_AUTHORIZATION': f'Bearer {refresh.access_token}'}
        assert api_client.get('/api/v1/me/', **header).status_code == 200

        response = api_client.put(
            f'{BASE}{user.pk}/',
            {'email': user.email, 'is_staff': True, 'is_superuser': False, 'is_active': False},
            content_type='application/json',
            **root_header,
        )
        assert response.status_code == 200

        rejected = api_client.get('/api/v1/me/', **header)
        assert rejected.status_code == 401
        assert '停用' in rejected.json()['message']

    def test_user_034_deactivated_user_cannot_refresh(self, api_client, user):
        """refresh 通道同口径：停用账号不能换新令牌。"""
        refresh = RefreshToken.for_user(user)  # type: ignore[misc]
        raw = str(refresh)
        User.objects.filter(pk=user.pk).update(is_active=False)

        response = api_client.post(
            '/api/v1/token/refresh/', {'refresh': raw}, content_type='application/json'
        )

        assert response.status_code == 401
        assert '停用' in response.json()['message']


@pytest.mark.django_db
class TestResetPassword:
    """USER-040 重置密码 + 旧令牌立即失效。"""

    def _token_issued_minutes_ago(self, user, minutes: int = 5) -> str:
        """构造一个「5 分钟前签发」的 access token，避免同秒边界导致用例不稳定。"""
        refresh = RefreshToken.for_user(user)  # type: ignore[misc]
        access = refresh.access_token
        access.set_iat(at_time=timezone.now() - timedelta(minutes=minutes))
        return str(access)

    def test_user_040_reset_changes_password(self, api_client, root_header, user):
        response = api_client.post(
            f'{BASE}{user.pk}/reset-password/',
            {'password': 'An0ther-pass-2026'},
            content_type='application/json',
            **root_header,
        )

        assert response.status_code == 200
        assert '需重新登录' in response.json()['message']
        assert authenticate(username='testuser', password='An0ther-pass-2026') is not None
        user.refresh_from_db()
        assert user.password_changed_at is not None

    def test_user_041_old_access_token_revoked(self, api_client, root_header, user):
        """核心安全断言：改密前的令牌不能继续用。"""
        old_token = self._token_issued_minutes_ago(user)
        header = {'HTTP_AUTHORIZATION': f'Bearer {old_token}'}
        assert api_client.get('/api/v1/me/', **header).status_code == 200

        api_client.post(
            f'{BASE}{user.pk}/reset-password/',
            {'password': 'An0ther-pass-2026'},
            content_type='application/json',
            **root_header,
        )

        rejected = api_client.get('/api/v1/me/', **header)
        assert rejected.status_code == 401
        assert '密码已变更' in rejected.json()['message']

    def test_user_042_new_token_after_reset_works(self, api_client, root_header, user):
        """改密后重新登录拿到的新令牌必须可用（不能把新会话也一起打死）。"""
        api_client.post(
            f'{BASE}{user.pk}/reset-password/',
            {'password': 'An0ther-pass-2026'},
            content_type='application/json',
            **root_header,
        )
        login = api_client.post(
            '/api/v1/login/',
            {'username': 'testuser', 'password': 'An0ther-pass-2026'},
            content_type='application/json',
        )
        token = login.json()['data']['access']

        me = api_client.get('/api/v1/me/', HTTP_AUTHORIZATION=f'Bearer {token}')
        assert me.status_code == 200

    def test_user_043_weak_password_400(self, api_client, root_header, user):
        response = api_client.post(
            f'{BASE}{user.pk}/reset-password/',
            {'password': '12345678'},
            content_type='application/json',
            **root_header,
        )

        assert response.status_code == 400

    def test_user_044_missing_password_422(self, api_client, root_header, user):
        response = api_client.post(
            f'{BASE}{user.pk}/reset-password/',
            {},
            content_type='application/json',
            **root_header,
        )

        assert response.status_code == 422


@pytest.mark.django_db
class TestUserDelete:
    """USER-050 删除：自己/最后一个超管/有文章 三种拦截 + 转移与强制两种放行。"""

    def test_user_050_cannot_delete_self(self, api_client, root_header, superuser):
        response = api_client.delete(f'{BASE}{superuser.pk}/', **root_header)

        assert response.status_code == 400
        assert '当前登录账号' in response.json()['message']

    def test_user_051_delete_other_superuser(self, api_client, root_header, superuser):
        """当前超管删另一个超管是允许的（「最后一个超管」保护不能误拦）。"""
        other = User.objects.create_superuser(username='root2', password='root2pass123')

        response = api_client.delete(f'{BASE}{other.pk}/', **root_header)

        assert response.status_code == 200
        assert not User.objects.filter(pk=other.pk).exists()

    def test_user_052_has_articles_409(self, api_client, root_header, user, make_article):
        make_article(user, 'u-052')

        response = api_client.delete(f'{BASE}{user.pk}/', **root_header)

        assert response.status_code == 409
        assert '1 篇文章' in response.json()['message']
        assert User.objects.filter(pk=user.pk).exists()

    def test_user_053_reassign_then_delete(self, api_client, root_header, user, make_article):
        make_article(user, 'u-053')
        target = User.objects.create_user(username='keeper', password='keeperpass123')

        response = api_client.delete(f'{BASE}{user.pk}/?reassign_to={target.pk}', **root_header)

        assert response.status_code == 200
        assert response.json()['data']['reassigned_articles'] == 1
        assert not User.objects.filter(pk=user.pk).exists()
        from articles.models import Article

        assert Article.objects.get(slug='u-053').author_id == target.pk

    def test_user_054_force_cascades_articles(self, api_client, root_header, user, make_article):
        make_article(user, 'u-054')

        response = api_client.delete(f'{BASE}{user.pk}/?force=true', **root_header)

        assert response.status_code == 200
        from articles.models import Article

        assert not Article.objects.filter(slug='u-054').exists()
        assert not User.objects.filter(pk=user.pk).exists()

    def test_user_055_delete_without_articles(self, api_client, root_header, user):
        response = api_client.delete(f'{BASE}{user.pk}/', **root_header)

        assert response.status_code == 200
        assert response.json()['data']['username'] == 'testuser'
        assert not User.objects.filter(pk=user.pk).exists()

    def test_user_056_delete_cleans_avatar(self, api_client, root_header, user, test_image):
        user.avatar = SimpleUploadedFile('a.jpg', test_image.read(), content_type='image/jpeg')
        user.save(update_fields=['avatar'])
        avatar_name = user.avatar.name
        storage = user.avatar.storage
        assert storage.exists(avatar_name)

        api_client.delete(f'{BASE}{user.pk}/', **root_header)

        assert not storage.exists(avatar_name)

    def test_user_057_reassign_to_self_400(self, api_client, root_header, user, make_article):
        make_article(user, 'u-057')

        response = api_client.delete(f'{BASE}{user.pk}/?reassign_to={user.pk}', **root_header)

        assert response.status_code == 400
        assert '不能把文章转移给被删除的用户' in response.json()['message']

    def test_user_058_target_not_found_404(self, api_client, root_header, user, make_article):
        make_article(user, 'u-058')

        response = api_client.delete(f'{BASE}{user.pk}/?reassign_to=999999', **root_header)

        assert response.status_code == 404
