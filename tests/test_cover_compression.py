"""封面压缩（``articles/covers.py``）与 ``recompress_covers`` 命令。

封面从"原样存储"改为"统一压成 WebP + 限制最长边"，这是详情页流量的最大头
（改造前 12 篇封面合计 16.5MB，单张最大 4MB）。覆盖：压缩生效、幂等（已达标原样
返回）、格式/扩展名一致、元数据剥离、透明通道保留、上传与更新两条路径都落 ``.webp``，
以及命令的 dry-run / --apply 行为。
"""
import hashlib
import io
from pathlib import Path

import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart
from django.utils import timezone
from PIL import Image

from articles.covers import CoverError, process_cover
from articles.models import Article

pytestmark = pytest.mark.django_db

MAX_PIXELS = 80_000_000
COVER_URL = '/api/v1/admin/articles/'


def encode(size=(40, 30), fmt='JPEG', color='red', **kwargs) -> bytes:
    buffer = io.BytesIO()
    Image.new('RGB', size, color=color).save(buffer, format=fmt, **kwargs)
    return buffer.getvalue()


def open_bytes(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def put_article(api_client, auth_header, article_id: int, data: dict):
    """multipart PUT（Django 6 测试客户端的 put() 不做 multipart 编码，须手工编码）。"""
    return api_client.put(
        f'{COVER_URL}{article_id}/',
        encode_multipart(BOUNDARY, data),
        content_type=MULTIPART_CONTENT,
        **auth_header,
    )


class TestProcessCover:
    """核心压缩管线。"""

    def test_jpeg_is_converted_to_webp_and_downscaled(self):
        """JPEG→WebP，且最长边被压到 COVER_MAX_LONG_EDGE 以内。"""
        raw = encode(size=(4000, 3000))

        result = process_cover(raw, 'jpg', max_pixels=MAX_PIXELS)

        assert result.ext == 'webp'
        assert result.data[:4] == b'RIFF' and result.data[8:12] == b'WEBP'
        assert max(result.width, result.height) == settings.COVER_MAX_LONG_EDGE
        assert len(result.data) < len(raw)

    def test_normalized_webp_is_returned_byte_identical(self):
        """已达标必须**原样返回** —— 这是导出→导入幂等的前提，去掉就会每轮掉画质。"""
        raw = process_cover(encode(), 'jpg', max_pixels=MAX_PIXELS).data

        again = process_cover(raw, 'webp', max_pixels=MAX_PIXELS)

        assert again.sha256 == hashlib.sha256(raw).hexdigest()
        assert again.data == raw

    def test_oversized_webp_is_downscaled(self):
        """已是 WebP 但超过最长边 → 仍要缩小（"达标"包含尺寸这一维）。"""
        raw = encode(size=(4000, 3000), fmt='WEBP')

        result = process_cover(raw, 'webp', max_pixels=MAX_PIXELS)

        assert max(result.width, result.height) == settings.COVER_MAX_LONG_EDGE
        assert result.data != raw

    def test_exif_orientation_is_applied_and_stripped(self):
        """Orientation=6 会转置宽高，且产物里不再带 EXIF。"""
        image = Image.new('RGB', (60, 40), color='blue')
        exif = Image.Exif()
        exif[0x0112] = 6
        buffer = io.BytesIO()
        image.save(buffer, format='JPEG', exif=exif)

        result = process_cover(buffer.getvalue(), 'jpg', max_pixels=MAX_PIXELS)

        assert (result.width, result.height) == (40, 60)
        assert not open_bytes(result.data).getexif()
        assert any('EXIF' in w for w in result.warnings)

    def test_no_false_exif_warning_without_orientation(self):
        """无 Orientation 时不得假阳报警（Pillow 12.x 的 exif_transpose 也返回副本）。"""
        result = process_cover(encode(), 'jpg', max_pixels=MAX_PIXELS)

        assert not any('EXIF' in w for w in result.warnings)

    def test_png_transparency_is_preserved(self):
        """带透明的 PNG 转 WebP 后仍保留 alpha 通道（不能压成不透明）。"""
        buffer = io.BytesIO()
        Image.new('RGBA', (40, 30), color=(255, 0, 0, 0)).save(buffer, format='PNG')

        result = process_cover(buffer.getvalue(), 'png', max_pixels=MAX_PIXELS)

        assert 'A' in open_bytes(result.data).convert('RGBA').getbands()

    def test_format_must_match_extension(self):
        """JPEG 字节命名为 .png → 拒绝（否则 nginx 会按扩展名发错 Content-Type）。"""
        with pytest.raises(CoverError, match='不一致'):
            process_cover(encode(fmt='JPEG'), 'png', max_pixels=MAX_PIXELS)

    def test_mpo_cover_is_accepted(self):
        """手机拍的 MPO（"JPEG + 附加帧"）必须放行 —— 真实数据里就有这种封面。

        回归：只认 JPEG 会让手机原图上传直接 400。
        """
        buffer = io.BytesIO()
        Image.new('RGB', (40, 30), color='red').save(
            buffer,
            format='MPO',
            save_all=True,
            append_images=[Image.new('RGB', (40, 30), color='blue')],
        )
        raw = buffer.getvalue()
        assert Image.open(io.BytesIO(raw)).format == 'MPO'  # 前提成立

        result = process_cover(raw, 'jpg', max_pixels=MAX_PIXELS)

        assert result.ext == 'webp'
        assert (result.width, result.height) == (40, 30)

    def test_rejects_unknown_extension(self):
        with pytest.raises(CoverError, match='仅支持'):
            process_cover(encode(fmt='JPEG'), 'gif', max_pixels=MAX_PIXELS)

    def test_rejects_non_image_bytes(self):
        with pytest.raises(CoverError, match='无法解析'):
            process_cover(b'not an image', 'jpg', max_pixels=MAX_PIXELS)

    def test_rejects_oversized_pixels(self):
        with pytest.raises(CoverError, match='像素数超限'):
            process_cover(encode(size=(4000, 3000)), 'jpg', max_pixels=1000)


class TestUploadPathCompresses:
    """上传端点落盘的就是压缩后的 WebP。"""

    def test_create_stores_webp(self, api_client, auth_header, test_image):
        raw = test_image.read()
        test_image.seek(0)

        response = api_client.post(
            COVER_URL,
            {
                'title': '测试文章',
                'slug': 'webp-cover',
                'publish_time': '2026-08-09T14:00:00Z',
                'is_published': True,
                'content': '正文',
                'cover': test_image,
            },
            **auth_header,
        )

        assert response.status_code == 201, response.json()
        article = Article.objects.get(slug='webp-cover')
        assert article.cover_image.name.endswith('.webp')
        with article.cover_image.open('rb') as handle:
            assert handle.read()[:4] == b'RIFF'
        # 哈希记的是**落盘字节**，不是源字节
        assert article.cover_image_sha256 != hashlib.sha256(raw).hexdigest()
        assert article.cover_image_name == 'test.jpg'  # 展示名仍是原始文件名

    def test_update_stores_webp_and_removes_old(
        self, api_client, auth_header, user, article_factory, media_root
    ):
        article = article_factory(user, slug='replace-cover', cover_bytes=encode())
        old_name = article.cover_image.name
        upload = SimpleUploadedFile('new.png', encode(fmt='PNG', color='green'), 'image/png')

        response = put_article(api_client, auth_header, article.pk, {'cover': upload})

        assert response.status_code == 200, response.json()
        article.refresh_from_db()
        assert article.cover_image.name.endswith('.webp')
        assert article.cover_image.name != old_name
        assert not (Path(media_root) / old_name).exists()


class TestRecompressCoversCommand:
    """存量封面批量重压。"""

    @pytest.fixture
    def legacy_article(self, user):
        """模拟"改造前"的文章：磁盘上是原始 JPEG，哈希记的是源字节。

        必须手工写原始字节 —— ``article_factory`` 现在也会压缩，造不出这个状态。
        """
        raw = encode(size=(3000, 2000))
        article = Article.objects.create(
            title='老文章',
            slug='legacy-cover',
            content='正文',
            publish_time=timezone.now(),
            author=user,
            cover_image_name='老封面.jpg',
            cover_image_sha256=hashlib.sha256(raw).hexdigest(),
        )
        article.cover_image.save('old-cover.jpg', SimpleUploadedFile('x', raw), save=False)
        article.save()
        return article, raw

    def test_dry_run_reports_without_writing(self, legacy_article, capsys):
        article, raw = legacy_article

        call_command('recompress_covers')

        out = capsys.readouterr().out
        assert 'dry-run' in out
        assert '未做任何改动' in out

        article.refresh_from_db()
        assert article.cover_image.name.endswith('.jpg')  # 未被替换
        with article.cover_image.open('rb') as handle:
            assert handle.read() == raw

    def test_apply_rewrites_to_smaller_webp(self, legacy_article, media_root):
        article, raw = legacy_article
        old_name = article.cover_image.name

        call_command('recompress_covers', '--apply')

        article.refresh_from_db()
        assert article.cover_image.name.endswith('.webp')
        with article.cover_image.open('rb') as handle:
            stored = handle.read()
        assert len(stored) < len(raw)
        assert article.cover_image_sha256 == hashlib.sha256(stored).hexdigest()
        assert not (Path(media_root) / old_name).exists()  # 旧文件已回收

    def test_apply_is_idempotent(self, legacy_article, capsys):
        """跑第二遍不得再次重写（已达标会被跳过），否则等于每轮都在掉画质。"""
        call_command('recompress_covers', '--apply')
        capsys.readouterr()

        call_command('recompress_covers', '--apply')

        assert '待重压 0 篇' in capsys.readouterr().out
