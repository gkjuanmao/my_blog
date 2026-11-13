"""在线状态测试：活跃时间写入、节流、窗口判定与故障降级。

口径：在线 = 最近 ``USER_ONLINE_WINDOW_SECONDS``（默认 900s）内有过一次
「携带有效令牌」的请求。前台公开页不鉴权，因此纯浏览不计入活跃。
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from users.models import User
from users.presence import is_online


@pytest.mark.django_db
class TestPresenceWrite:
    """USER-060 鉴权请求会刷新 last_seen_at，但按窗口节流。"""

    def test_user_060_authed_request_marks_seen(self, api_client, user, auth_header):
        assert user.last_seen_at is None

        response = api_client.get('/api/v1/me/', **auth_header)

        assert response.status_code == 200
        user.refresh_from_db()
        assert user.last_seen_at is not None
        assert (timezone.now() - user.last_seen_at).total_seconds() < 5

    def test_user_061_second_request_is_throttled(self, api_client, user, auth_header):
        """同一用户 60 秒内只写一次：第二次请求不能覆盖数据库里的值。"""
        api_client.get('/api/v1/me/', **auth_header)

        fixed = timezone.now() - timedelta(hours=1)
        User.objects.filter(pk=user.pk).update(last_seen_at=fixed)

        api_client.get('/api/v1/me/', **auth_header)

        user.refresh_from_db()
        assert user.last_seen_at == fixed

    def test_user_062_zero_throttle_always_writes(self, api_client, user, auth_header, settings):
        """节流配成 0 时退化为「每次都写」，用于排查在线状态不准。"""
        settings.USER_PRESENCE_THROTTLE_SECONDS = 0
        fixed = timezone.now() - timedelta(hours=1)
        User.objects.filter(pk=user.pk).update(last_seen_at=fixed)

        api_client.get('/api/v1/me/', **auth_header)

        user.refresh_from_db()
        assert user.last_seen_at > fixed

    def test_user_063_login_marks_seen_and_last_login(self, api_client, user):
        """登录是最明确的在线信号：last_seen_at 与 last_login 一起补上。"""
        response = api_client.post(
            '/api/v1/login/',
            {'username': 'testuser', 'password': 'testpass123'},
            content_type='application/json',
        )

        assert response.status_code == 200
        user.refresh_from_db()
        assert user.last_login is not None
        assert user.last_seen_at is not None

    def test_user_064_cache_failure_does_not_break_request(
        self, api_client, user, auth_header, monkeypatch
    ):
        """缓存挂了也要能正常请求：降级为「按 last_seen_at 判断」而不是 500。"""

        def _boom(*args, **kwargs):
            raise RuntimeError('cache down')

        monkeypatch.setattr('users.presence.cache.add', _boom)

        response = api_client.get('/api/v1/me/', **auth_header)

        assert response.status_code == 200
        user.refresh_from_db()
        assert user.last_seen_at is not None

    def test_user_065_anonymous_request_not_tracked(self, api_client, user):
        """公开接口不鉴权，不应把任何人标记成活跃。"""
        api_client.get('/api/v1/articles/')

        user.refresh_from_db()
        assert user.last_seen_at is None


class TestOnlineWindow:
    """USER-070 窗口判定（纯函数，注入固定 now，避免依赖真实时钟）。"""

    def test_user_070_boundary(self):
        now = timezone.now()

        assert is_online(now - timedelta(seconds=899), now=now) is True
        assert is_online(now - timedelta(seconds=900), now=now) is True
        assert is_online(now - timedelta(seconds=901), now=now) is False
        assert is_online(None, now=now) is False

    def test_user_071_window_is_configurable(self, settings):
        """窗口是配置项，改配置即改判定（900s 是产品决策，不是硬编码）。"""
        settings.USER_ONLINE_WINDOW_SECONDS = 60
        now = timezone.now()

        assert is_online(now - timedelta(seconds=30), now=now) is True
        assert is_online(now - timedelta(seconds=120), now=now) is False
