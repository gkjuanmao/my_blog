"""认证模块测试：POST /api/v1/login/。"""
import pytest


@pytest.mark.django_db
class TestLoginAPI:
    def test_auth_001_normal_login(self, api_client, user):
        """AUTH-001 正常登录。"""
        response = api_client.post(
            '/api/v1/login/',
            {'username': 'testuser', 'password': 'testpass123'},
            content_type='application/json',
        )

        assert response.status_code == 200
        data = response.json()
        assert data['code'] == 200
        assert 'access' in data['data']
        assert 'refresh' in data['data']

    def test_auth_002_wrong_username(self, api_client, user):
        """AUTH-002 用户名错误。"""
        response = api_client.post(
            '/api/v1/login/',
            {'username': 'wrong', 'password': 'testpass123'},
            content_type='application/json',
        )

        assert response.status_code == 401
        assert '用户名或密码错误' in response.json()['message']

    def test_auth_003_wrong_password(self, api_client, user):
        """AUTH-003 密码错误。"""
        response = api_client.post(
            '/api/v1/login/',
            {'username': 'testuser', 'password': 'wrong'},
            content_type='application/json',
        )

        assert response.status_code == 401
        assert '用户名或密码错误' in response.json()['message']

    def test_auth_004_missing_username(self, api_client):
        """AUTH-004 缺少 username。"""
        response = api_client.post(
            '/api/v1/login/',
            {'password': 'testpass123'},
            content_type='application/json',
        )

        assert response.status_code == 422

    def test_auth_005_missing_password(self, api_client):
        """AUTH-005 缺少 password。"""
        response = api_client.post(
            '/api/v1/login/',
            {'username': 'testuser'},
            content_type='application/json',
        )

        assert response.status_code == 422

    def test_auth_006_empty_username(self, api_client):
        """AUTH-006 username 为空。"""
        response = api_client.post(
            '/api/v1/login/',
            {'username': '', 'password': 'testpass123'},
            content_type='application/json',
        )

        assert response.status_code == 422
