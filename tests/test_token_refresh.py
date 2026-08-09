"""认证模块测试：POST /api/v1/token/refresh/。"""
from datetime import timedelta

import pytest
from ninja_jwt.tokens import RefreshToken


@pytest.mark.django_db
class TestTokenRefreshAPI:
    def test_auth_010_normal_refresh(self, api_client, user):
        """AUTH-010 正常刷新。"""
        refresh = RefreshToken.for_user(user)  # type: ignore[misc]
        response = api_client.post(
            '/api/v1/token/refresh/',
            {'refresh': str(refresh)},
            content_type='application/json',
        )

        assert response.status_code == 200
        assert 'access' in response.json()['data']

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
