"""本人修改密码测试：POST /api/v1/password/change/。

这组用例要钉住四条行为（都属于「改错一行就出安全事件」的级别）：

1. 必须验旧密码，否则令牌泄漏 = 账号被夺；
2. 改完自己不断线（返回的新令牌立刻可用），否则体验上是「改密即被踢」；
3. 改完旧 access 与旧 refresh 全部失效，否则等于没改；
4. 旧密码错误次数限流，防止拿着令牌爆破旧密码。
"""
from datetime import timedelta

import pytest
from django.utils import timezone
from ninja_jwt.tokens import RefreshToken

from users.models import User

BASE = '/api/v1/password/change/'
OLD = 'testpass123'
NEW = 'New-pass-2026'


def _refresh_of(user) -> str:
    return str(RefreshToken.for_user(user))  # type: ignore[misc]


@pytest.mark.django_db
class TestChangeOwnPassword:
    def test_auth_020_change_password_ok(self, api_client, auth_header, user):
        """AUTH-020 正常改密：200 且返回新的 access/refresh。"""
        response = api_client.post(
            BASE,
            {'old_password': OLD, 'new_password': NEW},
            content_type='application/json',
            **auth_header,
        )

        assert response.status_code == 200
        data = response.json()['data']
        assert data['access'] and data['refresh']
        user.refresh_from_db()
        assert user.check_password(NEW)
        assert user.password_changed_at is not None

    def test_auth_021_wrong_old_password(self, api_client, auth_header, user):
        """AUTH-021 旧密码错误：400 且密码不变。"""
        response = api_client.post(
            BASE,
            {'old_password': 'wrong-old-pass', 'new_password': NEW},
            content_type='application/json',
            **auth_header,
        )

        assert response.status_code == 400
        assert '当前密码不正确' in response.json()['message']
        user.refresh_from_db()
        assert user.check_password(OLD)

    def test_auth_022_requires_auth(self, api_client):
        """AUTH-022 匿名调用：401。"""
        response = api_client.post(
            BASE,
            {'old_password': OLD, 'new_password': NEW},
            content_type='application/json',
        )

        assert response.status_code == 401

    def test_auth_023_weak_new_password(self, api_client, auth_header, user):
        """AUTH-023 新密码是纯数字：400（走 AUTH_PASSWORD_VALIDATORS）。"""
        response = api_client.post(
            BASE,
            {'old_password': OLD, 'new_password': '12345678901'},
            content_type='application/json',
            **auth_header,
        )

        assert response.status_code == 400
        assert '数字' in response.json()['message'] or '常见' in response.json()['message']
        user.refresh_from_db()
        assert user.check_password(OLD)

    def test_auth_024_same_as_old(self, api_client, auth_header, user):
        """AUTH-024 新旧密码相同：400。"""
        response = api_client.post(
            BASE,
            {'old_password': OLD, 'new_password': OLD},
            content_type='application/json',
            **auth_header,
        )

        assert response.status_code == 400
        assert '不能与当前密码相同' in response.json()['message']

    def test_auth_025_new_token_works_immediately(self, api_client, auth_header, user):
        """AUTH-025 返回的新 access 立刻可用：改密不应把自己踢下线。"""
        response = api_client.post(
            BASE,
            {'old_password': OLD, 'new_password': NEW},
            content_type='application/json',
            **auth_header,
        )
        new_access = response.json()['data']['access']

        me = api_client.get('/api/v1/me/', HTTP_AUTHORIZATION=f'Bearer {new_access}')

        assert me.status_code == 200
        assert me.json()['data']['username'] == 'testuser'

    def test_auth_026_old_access_token_revoked(self, api_client, user):
        """AUTH-026 改密前的 access 失效：401 且提示密码已变更。

        旧令牌的 ``iat`` 特意回拨 5 分钟：判定是秒级严格小于，同一秒内签发的令牌
        会「幸存」，直接用真实时间构造会让用例在秒边界上随机失败。
        """
        old_token = RefreshToken.for_user(user).access_token  # type: ignore[misc]
        old_token.set_iat(at_time=timezone.now() - timedelta(minutes=5))
        old_access = str(old_token)
        fresh_access = str(RefreshToken.for_user(user).access_token)  # type: ignore[misc]

        response = api_client.post(
            BASE,
            {'old_password': OLD, 'new_password': NEW},
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {fresh_access}',
        )
        assert response.status_code == 200

        me = api_client.get('/api/v1/me/', HTTP_AUTHORIZATION=f'Bearer {old_access}')

        assert me.status_code == 401
        assert '密码已变更' in me.json()['message']

    def test_auth_027_old_refresh_token_revoked(self, api_client, auth_header, user):
        """AUTH-027 改密前的 refresh 全部进黑名单：换不到新 access。"""
        old_refresh = _refresh_of(user)

        change = api_client.post(
            BASE,
            {'old_password': OLD, 'new_password': NEW},
            content_type='application/json',
            **auth_header,
        )
        assert change.status_code == 200

        refreshed = api_client.post(
            '/api/v1/token/refresh/',
            {'refresh': old_refresh},
            content_type='application/json',
        )

        assert refreshed.status_code == 401

    def test_auth_028_old_password_throttled(self, api_client, auth_header, user):
        """AUTH-028 旧密码连续错 5 次后：429（防拿令牌爆破旧密码）。"""
        for _ in range(5):
            response = api_client.post(
                BASE,
                {'old_password': 'nope-wrong-1', 'new_password': NEW},
                content_type='application/json',
                **auth_header,
            )
            assert response.status_code == 400

        blocked = api_client.post(
            BASE,
            {'old_password': OLD, 'new_password': NEW},
            content_type='application/json',
            **auth_header,
        )

        assert blocked.status_code == 429
        assert '次数过多' in blocked.json()['message']
        user.refresh_from_db()
        assert user.check_password(OLD)

    def test_auth_029_success_clears_throttle(self, api_client, auth_header, user):
        """AUTH-029 成功改密清掉失败计数：此前错 4 次不应残留。"""
        for _ in range(4):
            api_client.post(
                BASE,
                {'old_password': 'nope-wrong-2', 'new_password': NEW},
                content_type='application/json',
                **auth_header,
            )

        ok = api_client.post(
            BASE,
            {'old_password': OLD, 'new_password': NEW},
            content_type='application/json',
            **auth_header,
        )
        assert ok.status_code == 200

        # 计数已清零：用新令牌再错一次仍应是 400 而不是 429
        new_access = ok.json()['data']['access']
        again = api_client.post(
            BASE,
            {'old_password': 'nope-wrong-3', 'new_password': 'Another-2026'},
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {new_access}',
        )

        assert again.status_code == 400

    def test_auth_030_other_user_token_unaffected(self, api_client, auth_header, user):
        """AUTH-030 改密只作废自己的令牌，他人会话不受影响（拉黑范围不越界）。"""
        other = User.objects.create_user(username='other', password='otherpass123')
        other_access = str(RefreshToken.for_user(other).access_token)  # type: ignore[misc]

        change = api_client.post(
            BASE,
            {'old_password': OLD, 'new_password': NEW},
            content_type='application/json',
            **auth_header,
        )
        assert change.status_code == 200

        me = api_client.get('/api/v1/me/', HTTP_AUTHORIZATION=f'Bearer {other_access}')

        assert me.status_code == 200
        assert me.json()['data']['username'] == 'other'

    def test_auth_031_inactive_user_rejected(self, api_client, user):
        """AUTH-031 已停用账号即使持有效令牌也不能改密。"""
        access = str(RefreshToken.for_user(user).access_token)  # type: ignore[misc]
        User.objects.filter(pk=user.pk).update(is_active=False)

        response = api_client.post(
            BASE,
            {'old_password': OLD, 'new_password': NEW},
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {access}',
        )

        assert response.status_code == 401
        assert '停用' in response.json()['message']
