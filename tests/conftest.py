"""pytest 全局 Fixture：Django 测试客户端、用户、JWT 认证头与测试文件。"""
import hashlib
import io
import zipfile

import pytest
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone
from ninja_jwt.tokens import RefreshToken
from PIL import Image

from articles.models import Article
from users.models import User


@pytest.fixture(autouse=True)
def media_root(tmp_path, settings):
    """将 MEDIA_ROOT 隔离到临时目录，避免测试上传的文件写进真实 media/。"""
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


@pytest.fixture(autouse=True)
def archive_root(tmp_path, settings):
    """把归档根目录隔离到临时目录，避免导出/暂存产物写进仓库。"""
    settings.ARCHIVE_ROOT = str(tmp_path / 'archives')
    return tmp_path / 'archives'


@pytest.fixture(autouse=True)
def clear_cache():
    """清空缓存，避免登录限流计数等缓存状态跨用例污染。"""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


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


# --------------------------------------------------------------------------- 归档相关


@pytest.fixture
def staff_user(db) -> User:
    """带 is_staff 的用户（归档端点要求 staff）。"""
    return User.objects.create_user(
        username='staffuser',
        password='staffpass123',
        email='staff@example.com',
        is_staff=True,
    )


@pytest.fixture
def staff_header(staff_user) -> dict:
    """staff 用户的 JWT 认证头。"""
    refresh = RefreshToken.for_user(staff_user)  # type: ignore[misc]
    return {'HTTP_AUTHORIZATION': f'Bearer {refresh.access_token}'}


@pytest.fixture
def archive_settings(settings):
    """归档测试用的宽松/收紧设置（导入间隔置 0 以便连续导入）。"""
    settings.ARCHIVE_IMPORT_MIN_INTERVAL_SECONDS = 0
    settings.ARCHIVE_STAGING_TTL_SECONDS = 600
    settings.ARCHIVE_TICKET_TTL_SECONDS = 600
    return settings


@pytest.fixture
def jpeg_factory():
    """生成 JPEG 字节；可指定尺寸与 EXIF Orientation。"""

    def _factory(size=(40, 30), color='red', orientation=None) -> bytes:
        img = Image.new('RGB', size, color=color)
        buffer = io.BytesIO()
        if orientation is None:
            img.save(buffer, format='JPEG')
        else:
            exif = Image.Exif()
            exif[0x0112] = orientation
            img.save(buffer, format='JPEG', exif=exif)
        return buffer.getvalue()

    return _factory


@pytest.fixture
def make_zip():
    """用 {条目名: 字节} 构造一个内存 zip。"""

    def _factory(files: dict, *, compress=zipfile.ZIP_DEFLATED) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', compress) as zf:
            for name, payload in files.items():
                zf.writestr(name, payload)
        return buffer.getvalue()

    return _factory


@pytest.fixture
def article_factory():
    """创建带真实媒体文件的文章（`*_sha256` 按源字节写入）。"""

    def _factory(
        user,
        *,
        slug='sample-slug',
        title='示例游记',
        cover_bytes=b'',
        pdf_bytes=b'%PDF-1.4 hello',
        published=True,
    ):
        article = Article(
            title=title,
            slug=slug,
            summary='这是摘要',
            publish_time=timezone.now(),
            location='某地',
            author=user,
            is_published=published,
            cover_image_name='封面.jpg',
            cover_image_sha256=hashlib.sha256(cover_bytes).hexdigest(),
            file_name='附件.pdf',
            file_sha256=hashlib.sha256(pdf_bytes).hexdigest(),
        )
        article.cover_image.save('cover.jpg', ContentFile(cover_bytes), save=False)
        article.file.save('attachment.pdf', ContentFile(pdf_bytes), save=False)
        article.save()
        return article

    return _factory


@pytest.fixture
def zip_bytes():
    """FileResponse 在测试里只有 streaming_content，没有 .content。"""

    def _factory(response) -> bytes:
        return b''.join(response.streaming_content)

    return _factory


@pytest.fixture
def make_raw_zip():
    """用 ZipInfo 构造 zip，可自定义 flag_bits / external_attr（恶意包测试用）。"""

    def _factory(entries: list[tuple[str, bytes]], *, raw: bool = False) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as zf:
            for name, payload in entries:
                if raw:
                    info = zipfile.ZipInfo(name)
                    info.compress_type = zipfile.ZIP_STORED
                    zf.writestr(info, payload)
                else:
                    zf.writestr(name, payload)
        return buffer.getvalue()

    return _factory
