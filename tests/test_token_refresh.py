"""认证模块测试：POST /api/v1/token/refresh/。"""
from datetime import timedelta

import pytest
from ninja_jwt.tokens import RefreshToken


@pytest.mark.django_db
class TestTokenRefreshAPI:
    def test_auth_010_normal_refresh(self, api_client, user):
        """AUTH-010 正常刷新，返回新 access 与轮换后的 refresh。"""
        refresh = RefreshToken.for_user(user)  # type: ignore[misc]
        response = api_client.post(
            '/api/v1/token/refresh/',
            {'refresh': str(refresh)},
            content_type='application/json',
        )

        assert response.status_code == 200
        data = response.json()['data']
        assert 'access' in data
        assert 'refresh' in data
        assert data['refresh'] != str(refresh)

    def test_auth_011_expired_token(self, api_client, user):
        """AUTH-011 token 过期。"""
        refresh = RefreshToken.for_user(user)  # type: ignore[misc]
        refresh.set_exp(lifetime=timedelta(seconds=-10))
        response = api_client.post(
            '/api/v1/token/refresh/',
            {'refresh': str(refresh)},
            content_type='application/json',
        )

        assert response.status_code == 401
        assert '过期' in response.json()['message']

    def test_auth_012_invalid_token(self, api_client):
        """AUTH-012 无效 token。"""
        response = api_client.post(
            '/api/v1/token/refresh/',
            {'refresh': 'invalid_token_string'},
            content_type='application/json',
        )

        assert response.status_code == 401
        assert '无效' in response.json()['message']

    def test_auth_013_missing_refresh(self, api_client):
        """AUTH-013 缺少 refresh 字段。"""
        response = api_client.post(
            '/api/v1/token/refresh/',
            {},
            content_type='application/json',
        )

        assert response.status_code == 422

    def test_auth_014_rotated_refresh_blacklisted(self, api_client, user):
        """AUTH-014 轮换后旧 refresh token 失效（进入黑名单）。"""
        refresh = RefreshToken.for_user(user)  # type: ignore[misc]
        old_refresh = str(refresh)

        first = api_client.post(
            '/api/v1/token/refresh/',
            {'refresh': old_refresh},
            content_type='application/json',
        )
        assert first.status_code == 200
        new_refresh = first.json()['data']['refresh']

        # 旧 token 已作废
        replay = api_client.post(
            '/api/v1/token/refresh/',
            {'refresh': old_refresh},
            content_type='application/json',
        )
        assert replay.status_code == 401

        # 新 token 可正常继续使用
        next_call = api_client.post(
            '/api/v1/token/refresh/',
            {'refresh': new_refresh},
            content_type='application/json',
        )
        assert next_call.status_code == 200
