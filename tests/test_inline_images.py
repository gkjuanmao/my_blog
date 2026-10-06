"""内联图片：压缩、内容寻址落盘、URL 归一化与孤儿清理。"""
import hashlib
import io
import os
import time

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.utils import timezone
from PIL import Image

from articles.images import (
    extract_inline_names,
    normalize_inline_name,
    process_inline_image,
    store_inline_image,
)
from articles.models import Article


def _png_bytes(size=(30, 20), color='blue') -> bytes:
    buffer = io.BytesIO()
    Image.new('RGB', size, color=color).save(buffer, format='PNG')
    return buffer.getvalue()


def _webp_bytes(size=(30, 20), color='green') -> bytes:
    buffer = io.BytesIO()
    Image.new('RGB', size, color=color).save(buffer, format='WEBP')
    return buffer.getvalue()


def _upload(name: str, data: bytes, content_type: str):
    return SimpleUploadedFile(name, data, content_type=content_type)


def _inline_path(name: str) -> str:
    from django.conf import settings

    return os.path.join(str(settings.MEDIA_ROOT), settings.INLINE_IMAGE_DIR, name)


def _write_inline(name: str, data: bytes, *, age_hours: float = 100) -> str:
    path = _inline_path(name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as handle:
        handle.write(data)
    old = time.time() - age_hours * 3600
    os.utime(path, (old, old))
    return path


@pytest.mark.django_db
class TestUploadEndpoint:
    def test_upload_compresses_to_webp(self, api_client, staff_header):
        response = api_client.post(
            '/api/v1/admin/articles/images/',
            {'image': _upload('pic.png', _png_bytes((800, 600)), 'image/png')},
            **staff_header,
        )

        assert response.status_code == 200
        data = response.json()['data']
        assert data['url'].startswith('/media/inline/')
        assert data['width'] == 800
        assert data['height'] == 600
        assert data['bytes'] > 0

        stored = _inline_path(os.path.basename(data['url']))
        assert os.path.isfile(stored)
        with open(stored, 'rb') as handle:
            assert handle.read(4) == b'RIFF'  # WebP 容器魔数

    def test_upload_requires_staff(self, api_client, plain_header):
        response = api_client.post(
            '/api/v1/admin/articles/images/',
            {'image': _upload('pic.png', _png_bytes(), 'image/png')},
            **plain_header,
        )

        assert response.status_code == 403

    def test_upload_rejects_non_image_extension(self, api_client, staff_header):
        response = api_client.post(
            '/api/v1/admin/articles/images/',
            {'image': _upload('note.txt', b'hello', 'text/plain')},
            **staff_header,
        )

        assert response.status_code == 400

    def test_upload_rejects_too_many_pixels(self, api_client, staff_header, settings):
        settings.INLINE_IMAGE_MAX_PIXELS = 100

        response = api_client.post(
            '/api/v1/admin/articles/images/',
            {'image': _upload('pic.png', _png_bytes((30, 20)), 'image/png')},
            **staff_header,
        )

        assert response.status_code == 400
        assert '像素' in response.json()['message']

    def test_same_image_dedupes_to_same_url(self, api_client, staff_header):
        payload = _png_bytes((64, 64))
        first = api_client.post(
            '/api/v1/admin/articles/images/',
            {'image': _upload('a.png', payload, 'image/png')},
            **staff_header,
        ).json()['data']['url']
        second = api_client.post(
            '/api/v1/admin/articles/images/',
            {'image': _upload('b.png', payload, 'image/png')},
            **staff_header,
        ).json()['data']['url']

        assert first == second


class TestProcessInlineImage:
    def test_exif_orientation_removed(self, jpeg_factory):
        """带 Orientation 的 JPEG：结果不得残留 EXIF。"""
        processed = process_inline_image(jpeg_factory(orientation=6), 'jpg')

        image = Image.open(io.BytesIO(processed.data))
        assert image.format == 'WEBP'
        assert 'exif' not in (image.info or {})

    def test_resizes_long_edge(self, settings):
        settings.INLINE_IMAGE_MAX_LONG_EDGE = 50

        processed = process_inline_image(_png_bytes((200, 100)), 'png')

        assert max(processed.width, processed.height) == 50

    def test_canonical_webp_returned_as_is(self):
        """已规范（WebP + 尺寸达标 + 无 EXIF/ICC）的输入原样返回（幂等固定点）。"""
        data = _webp_bytes((40, 30))

        processed = process_inline_image(data, 'webp')

        assert processed.data == data

    def test_format_must_match_extension(self):
        from articles.images import InlineImageError

        with pytest.raises(InlineImageError):
            process_inline_image(_png_bytes(), 'jpg')

    def test_store_is_content_addressed_and_atomic(self):
        processed = process_inline_image(_png_bytes(), 'png')
        rel = store_inline_image(processed.data)

        expected = hashlib.sha256(processed.data).hexdigest()[:32]
        assert rel == f'inline/{expected}.webp'
        # 目录里不应残留临时文件
        entries = os.listdir(os.path.dirname(_inline_path('x')))
        assert [name for name in entries if name.endswith('.tmp')] == []


class TestNormalizeInlineName:
    @pytest.mark.parametrize(
        'src',
        [
            '/media/inline/abc123.webp',
            'media/inline/abc123.webp',
            'https://host/media/inline/abc123.webp',
            '//host/media/inline/abc123.webp',
            '/MEDIA/Inline/ABC123.webp',
            '/media/inline/abc123.webp?x=1#frag',
        ],
    )
    def test_matches_variants(self, src):
        assert normalize_inline_name(src) == 'abc123.webp'

    @pytest.mark.parametrize(
        'src',
        ['/media/covers/a.jpg', '/media/inline/', '/media/inline/sub/a.webp', 'https://h/x.png'],
    )
    def test_rejects_non_inline(self, src):
        assert normalize_inline_name(src) is None

    def test_extract_from_html(self):
        html = (
            '<p><img src="/media/inline/a.webp" loading="lazy">'
            '<img src="https://h/media/inline/b.webp"></p>'
        )

        assert extract_inline_names(html) == {'a.webp', 'b.webp'}


@pytest.mark.django_db
class TestPurgeCommand:
    def _article(self, user, content: str) -> Article:
        return Article.objects.create(
            title='引用', slug=f'slug-{abs(hash(content)) % 100000}', content=content,
            publish_time=timezone.now(), author=user,
        )

    def test_referenced_image_not_deleted(self, user):
        _write_inline('keep.webp', b'RIFFkeep')
        self._article(user, '![x](/media/inline/keep.webp)')

        call_command('purge_inline_images', '--delete')

        assert os.path.isfile(_inline_path('keep.webp'))

    def test_orphan_deleted(self, user):
        _write_inline('orphan.webp', b'RIFForphan')
        self._article(user, '![x](/media/inline/keep.webp)')
        _write_inline('keep.webp', b'RIFFkeep')

        call_command('purge_inline_images', '--delete')

        assert not os.path.isfile(_inline_path('orphan.webp'))
        assert os.path.isfile(_inline_path('keep.webp'))

    def test_grace_period_protects_new_files(self, user):
        _write_inline('fresh.webp', b'RIFFfresh', age_hours=0)

        call_command('purge_inline_images', '--delete')

        assert os.path.isfile(_inline_path('fresh.webp'))

    def test_dry_run_keeps_everything(self, user):
        _write_inline('orphan.webp', b'RIFForphan')

        call_command('purge_inline_images')

        assert os.path.isfile(_inline_path('orphan.webp'))

    def test_fail_closed_when_extractor_returns_empty(self, user, monkeypatch):
        """提取器失效（提取空 + 字面量非空）时必须中止且不删任何文件。"""
        _write_inline('referenced.webp', b'RIFFref')
        self._article(user, '![x](/media/inline/referenced.webp)')

        import articles.management.commands.purge_inline_images as purge

        monkeypatch.setattr(purge, 'extract_inline_names', lambda html: set())

        call_command('purge_inline_images', '--delete')

        assert os.path.isfile(_inline_path('referenced.webp'))

    def test_both_empty_allows_cleanup(self, user):
        """确实没有引用（正文被清空）时不得死锁：应能正常清理。"""
        _write_inline('orphan.webp', b'RIFForphan')

        call_command('purge_inline_images', '--delete')

        assert not os.path.isfile(_inline_path('orphan.webp'))
