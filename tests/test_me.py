"""认证模块测试：GET /api/v1/me/。"""
from datetime import timedelta

import pytest
from ninja_jwt.tokens import RefreshToken


@pytest.mark.django_db
class TestMeAPI:
    def test_auth_016_get_user_info(self, api_client, auth_header):
        """AUTH-016 正常获取用户信息。"""
        response = api_client.get('/api/v1/me/', **auth_header)

        assert response.status_code == 200
        data = response.json()['data']
        assert data['username'] == 'testuser'
        assert data['email'] == 'test@example.com'
        assert 'password' not in data

    def test_auth_017_no_token(self, api_client):
        """AUTH-017 未携带 Token。"""
        response = api_client.get('/api/v1/me/')

        assert response.status_code == 401

    def test_auth_018_invalid_token(self, api_client):
        """AUTH-018 Token 格式错误。"""
        response = api_client.get('/api/v1/me/', HTTP_AUTHORIZATION='Bearer invalid_token')

        assert response.status_code == 401
        assert '无效' in response.json()['message']

    def test_auth_019_expired_token(self, api_client, user):
        """AUTH-019 Token 过期。"""
        refresh = RefreshToken.for_user(user)  # type: ignore[misc]
        token = refresh.access_token
        token.set_exp(lifetime=timedelta(seconds=-10))
        response = api_client.get('/api/v1/me/', HTTP_AUTHORIZATION=f'Bearer {token}')

        assert response.status_code == 401
        assert '过期' in response.json()['message']
