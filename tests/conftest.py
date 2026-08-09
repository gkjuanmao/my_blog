"""pytest 全局 Fixture：Django 测试客户端、用户、JWT 认证头与测试文件。"""
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from ninja_jwt.tokens import RefreshToken
from PIL import Image

from users.models import User


@pytest.fixture
def api_client() -> Client:
    """Django 测试客户端。"""
    return Client()


@pytest.fixture
def user(db) -> User:
    """创建测试用户。"""
    return User.objects.create_user(
        username='testuser',
        password='testpass123',
        email='test@example.com',
    )


@pytest.fixture
def auth_header(user) -> dict:
    """JWT 认证请求头。"""
    refresh = RefreshToken.for_user(user)  # type: ignore[misc]
    return {'HTTP_AUTHORIZATION': f'Bearer {refresh.access_token}'}


@pytest.fixture
def test_image() -> SimpleUploadedFile:
    """生成 100x100 红色 JPEG 图片。"""
    img = Image.new('RGB', (100, 100), color='red')
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG')
    buffer.seek(0)
    return SimpleUploadedFile('test.jpg', buffer.read(), content_type='image/jpeg')


@pytest.fixture
def test_pdf() -> SimpleUploadedFile:
    """生成 100KB PDF 文件。"""
    content = b'%PDF-1.4\n' + b'x' * 102400
    return SimpleUploadedFile('test.pdf', content, content_type='application/pdf')
