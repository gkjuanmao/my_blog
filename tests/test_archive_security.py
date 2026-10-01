"""归档安全闸门：zip slip、限制、编码、字段校验、并发锁。"""
import io
import json
import zipfile
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from articles.models import ArchiveStaging, Article

pytestmark = pytest.mark.django_db

STAGE_URL = '/api/v1/admin/articles/import/stage/'
COMMIT_URL = '/api/v1/admin/articles/import/commit/'


def _upload(payload: bytes, name='pkg.zip'):
    return SimpleUploadedFile(name, payload, content_type='application/zip')


def stage(api_client, staff_header, payload: bytes, strategy='skip'):
    """上传压缩包并断言成功（失败时把响应体暴露出来便于定位）。"""
    response = api_client.post(
        STAGE_URL,
        {'file': _upload(payload), 'strategy': strategy},
        **staff_header,
    )
    assert response.status_code == 200, response.json()
    return response


def stage_raw(api_client, staff_header, payload: bytes, strategy='skip'):
    """上传压缩包但不断言状态码（包级拒绝用例用）。"""
    return api_client.post(
        STAGE_URL,
        {'file': _upload(payload), 'strategy': strategy},
        **staff_header,
    )


def article_json(**overrides) -> bytes:
    payload = {
        'title': '安全测试',
        'slug': 'security-case',
        'publish_time': timezone.now().isoformat(),
        'cover': {'file': 'cover.jpg'},
        'attachment': {'file': 'attachment.pdf'},
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False).encode()


@pytest.fixture
def archive_settings(settings):
    settings.ARCHIVE_IMPORT_MIN_INTERVAL_SECONDS = 0
    settings.ARCHIVE_STAGING_TTL_SECONDS = 600
    settings.ARCHIVE_TICKET_TTL_SECONDS = 600
    return settings


@pytest.fixture
def package(make_zip, jpeg_factory):
    """一个合法的默认包。"""
    return make_zip({
        'articles/001-s/article.json': article_json(),
        'articles/001-s/cover.jpg': jpeg_factory(),
        'articles/001-s/attachment.pdf': b'%PDF-1.4 x',
    })


# --------------------------------------------------------------------------- 包级拒绝


class TestPackageLevelRejection:
    def test_zip_slip_relative(
        self, api_client, staff_header, make_zip, jpeg_factory, archive_settings
    ):
        payload = make_zip({
            '../evil/article.json': article_json(),
            '../evil/cover.jpg': jpeg_factory(),
            '../evil/attachment.pdf': b'x',
        })
        response = stage_raw(api_client, staff_header, payload)
        assert response.status_code == 400
        assert '路径穿越' in response.json()['message']

    def test_zip_slip_absolute(self, api_client, staff_header, make_raw_zip, archive_settings):
        payload = make_raw_zip([('/etc/passwd', b'root:x:0:0')], raw=True)
        response = stage_raw(api_client, staff_header, payload)
        assert response.status_code == 400

    def test_backslash_is_normalized_then_rejected(
        self, api_client, staff_header, make_raw_zip, archive_settings
    ):
        """Windows 风格分隔符先归一化，再做穿越判定（兼容 + 安全）。"""
        payload = make_raw_zip([('..\\evil\\article.json', b'{}')], raw=True)
        response = stage_raw(api_client, staff_header, payload)
        assert response.status_code == 400

    def test_duplicate_entry_case_variant(
        self, api_client, staff_header, make_zip, jpeg_factory, archive_settings
    ):
        payload = make_zip({
            'articles/001-d/article.json': article_json(),
            'articles/001-d/ARTICLE.JSON': article_json(),
            'articles/001-d/cover.jpg': jpeg_factory(),
            'articles/001-d/attachment.pdf': b'x',
        })
        response = stage_raw(api_client, staff_header, payload)
        assert response.status_code == 400
        assert '重复条目' in response.json()['message']

    def test_entry_count_limit(self, api_client, staff_header, package, settings, archive_settings):
        settings.ARCHIVE_MAX_ENTRIES = 2
        response = stage_raw(api_client, staff_header, package)
        assert response.status_code == 400
        assert '条目数' in response.json()['message']

    def test_total_uncompressed_limit_counts_real_bytes(
        self, api_client, staff_header, make_zip, jpeg_factory, settings, archive_settings
    ):
        """RT-13：按**真实**解压字节计费，而不是信任声明值/压缩后大小。"""
        bloated = b'\0' * 200_000  # 高度可压缩
        payload = make_zip({
            'articles/001-b/article.json': article_json(),
            'articles/001-b/cover.jpg': jpeg_factory(),
            'articles/001-b/attachment.pdf': bloated,
        })
        assert len(payload) < 5_000  # 压缩后极小
        # 放宽压缩比，专门验证"按真实解压字节计费"这条路径
        settings.ARCHIVE_MAX_COMPRESSION_RATIO = 100_000
        settings.ARCHIVE_MAX_TOTAL_UNCOMPRESSED = 1_000
        response = stage_raw(api_client, staff_header, payload)
        assert response.status_code == 400
        assert '解压总量' in response.json()['message']

    def test_member_size_limit(
        self, api_client, staff_header, make_zip, jpeg_factory, settings, archive_settings
    ):
        settings.ARCHIVE_MAX_MEMBER_BYTES = 100
        payload = make_zip({
            'articles/001-m/article.json': article_json(),
            'articles/001-m/cover.jpg': jpeg_factory(),
            'articles/001-m/attachment.pdf': b'x' * 500,
        })
        response = stage_raw(api_client, staff_header, payload)
        assert response.status_code == 400

    def test_compression_ratio_limit(
        self, api_client, staff_header, make_zip, jpeg_factory, settings, archive_settings
    ):
        settings.ARCHIVE_MAX_COMPRESSION_RATIO = 1
        payload = make_zip({
            'articles/001-c/article.json': article_json(),
            'articles/001-c/cover.jpg': jpeg_factory(),
            'articles/001-c/attachment.pdf': b'A' * 10_000,
        })
        response = stage_raw(api_client, staff_header, payload)
        assert response.status_code == 400

    def test_not_a_zip(self, api_client, staff_header, archive_settings):
        response = stage_raw(api_client, staff_header, b'this is not a zip')
        assert response.status_code == 400
        assert 'ZIP' in response.json()['message']

    def test_no_article_json(self, api_client, staff_header, make_zip, archive_settings):
        response = stage_raw(api_client, staff_header, make_zip({'readme.txt': b'hi'}))
        assert response.status_code == 400
        assert 'article.json' in response.json()['message']

    def test_requires_staff(self, api_client, auth_header, package):
        response = api_client.post(STAGE_URL, {'file': _upload(package)}, **auth_header)
        assert response.status_code == 403


# --------------------------------------------------------------------------- 条目级失败


class TestItemLevelFailures:
    def _stage_report(self, api_client, staff_header, payload):
        return stage(api_client, staff_header, payload).json()['data']

    def test_bad_attachment_extension_only_fails_that_item(
        self, api_client, staff_header, make_zip, jpeg_factory, archive_settings
    ):
        payload = make_zip({
            'articles/001-x/article.json': article_json(slug='bad-ext'),
            'articles/001-x/cover.jpg': jpeg_factory(),
            'articles/001-x/attachment.exe': b'MZ',
        })
        report = self._stage_report(api_client, staff_header, payload)
        failed = [i for i in report['items'] if i['action'] == 'failed'][0]
        assert any('attachment' in e for e in failed['errors'])

    def test_html_attachment_is_accepted_as_legacy_with_warning(
        self, api_client, staff_header, make_zip, jpeg_factory, archive_settings
    ):
        """D23：存量 HTML 走遗留通道（可回导 + 强制下载 + 告警），上传侧仍拒绝。"""
        payload = make_zip({
            'articles/001-h/article.json': article_json(slug='legacy-html'),
            'articles/001-h/cover.jpg': jpeg_factory(),
            'articles/001-h/attachment.html': b'<html><script>alert(1)</script></html>',
        })
        dry = self._stage_report(api_client, staff_header, payload)
        assert dry['items'][0]['action'] == 'create'
        assert any('HTML' in w for w in dry['items'][0]['warnings'])

    def test_oversize_title_fails_only_that_item(
        self, api_client, staff_header, make_zip, jpeg_factory, archive_settings
    ):
        payload = make_zip({
            'articles/001-1/article.json': article_json(slug='too-long', title='x' * 300),
            'articles/001-1/cover.jpg': jpeg_factory(),
            'articles/001-1/attachment.pdf': b'%PDF',
            'articles/002-2/article.json': article_json(slug='fine'),
            'articles/002-2/cover.jpg': jpeg_factory(),
            'articles/002-2/attachment.pdf': b'%PDF',
        })
        report = self._stage_report(api_client, staff_header, payload)
        actions = {item['path']: item['action'] for item in report['items']}
        assert actions['articles/001-1'] == 'failed'
        assert actions['articles/002-2'] == 'create'

    def test_invalid_slug_is_rejected(
        self, api_client, staff_header, make_zip, jpeg_factory, archive_settings
    ):
        payload = make_zip({
            'articles/001-s/article.json': article_json(slug='非法 Slug!'),
            'articles/001-s/cover.jpg': jpeg_factory(),
            'articles/001-s/attachment.pdf': b'%PDF',
        })
        report = self._stage_report(api_client, staff_header, payload)
        assert report['items'][0]['action'] == 'failed'
        assert any('slug' in e for e in report['items'][0]['errors'])

    def test_non_bool_is_published_is_rejected(
        self, api_client, staff_header, make_zip, jpeg_factory, archive_settings
    ):
        payload = make_zip({
            'articles/001-s/article.json': article_json(is_published='true'),
            'articles/001-s/cover.jpg': jpeg_factory(),
            'articles/001-s/attachment.pdf': b'%PDF',
        })
        report = self._stage_report(api_client, staff_header, payload)
        assert report['items'][0]['action'] == 'failed'
        assert any('布尔' in e for e in report['items'][0]['errors'])

    def test_duplicate_slug_in_package(
        self, api_client, staff_header, make_zip, jpeg_factory, archive_settings
    ):
        payload = make_zip({
            'articles/001-a/article.json': article_json(slug='same-slug'),
            'articles/001-a/cover.jpg': jpeg_factory(),
            'articles/001-a/attachment.pdf': b'%PDF',
            'articles/002-b/article.json': article_json(slug='same-slug'),
            'articles/002-b/cover.jpg': jpeg_factory(),
            'articles/002-b/attachment.pdf': b'%PDF',
        })
        report = self._stage_report(api_client, staff_header, payload)
        statuses = sorted(item['action'] for item in report['items'])
        assert statuses == ['create', 'failed']
        failed = [i for i in report['items'] if i['action'] == 'failed'][0]
        assert any('slug 重复' in e for e in failed['errors'])

    def test_nested_article_json_is_ambiguous(
        self, api_client, staff_header, make_zip, jpeg_factory, archive_settings
    ):
        payload = make_zip({
            'articles/001-n/article.json': article_json(slug='nested'),
            'articles/001-n/cover.jpg': jpeg_factory(),
            'articles/001-n/attachment.pdf': b'%PDF',
            'articles/001-n/backup/article.json': article_json(slug='nested-backup'),
        })
        report = self._stage_report(api_client, staff_header, payload)
        assert any(
            '嵌套' in e for item in report['items'] for e in item['errors']
        )

    def test_missing_cover_fails_item(self, api_client, staff_header, make_zip, archive_settings):
        payload = make_zip({'articles/001-s/article.json': article_json()})
        report = self._stage_report(api_client, staff_header, payload)
        assert report['items'][0]['action'] == 'failed'

    def test_pixel_cap_rejects_large_image(
        self, api_client, staff_header, make_zip, jpeg_factory, settings, archive_settings
    ):
        settings.ARCHIVE_MAX_IMAGE_PIXELS = 1
        payload = make_zip({
            'articles/001-p/article.json': article_json(slug='huge-pixels'),
            'articles/001-p/cover.jpg': jpeg_factory(size=(100, 100)),
            'articles/001-p/attachment.pdf': b'%PDF',
        })
        report = self._stage_report(api_client, staff_header, payload)
        assert report['items'][0]['action'] == 'failed'
        assert any('像素' in e for e in report['items'][0]['errors'])

    def test_cover_extension_mismatch_is_rejected(
        self, api_client, staff_header, make_zip, jpeg_factory, archive_settings
    ):
        """扩展名说 png，内容其实是 jpeg → 必须失败（不靠扩展名相信内容）。"""
        payload = make_zip({
            'articles/001-m/article.json': article_json(slug='mismatch'),
            'articles/001-m/cover.png': jpeg_factory(),
            'articles/001-m/attachment.pdf': b'%PDF',
        })
        report = self._stage_report(api_client, staff_header, payload)
        assert report['items'][0]['action'] == 'failed'
        assert any('格式' in e for e in report['items'][0]['errors'])


# --------------------------------------------------------------------------- 编码


class TestEncodings:
    def _stage_payload(self, api_client, staff_header, payload):
        return stage(api_client, staff_header, payload)

    def test_gbk_article_json_is_accepted(
        self, api_client, staff_header, make_zip, jpeg_factory, archive_settings
    ):
        raw = json.dumps(
            {
                'title': '中文标题',
                'slug': 'gbk-case',
                'publish_time': timezone.now().isoformat(),
                'cover': {'file': 'cover.jpg'},
                'attachment': {'file': 'attachment.pdf'},
            },
            ensure_ascii=False,
        ).encode('gbk')
        payload = make_zip({
            'articles/001-g/article.json': raw,
            'articles/001-g/cover.jpg': jpeg_factory(),
            'articles/001-g/attachment.pdf': b'%PDF',
        })
        report = self._stage_payload(api_client, staff_header, payload).json()['data']
        assert report['items'][0]['action'] == 'create'

    def test_utf8_bom_is_accepted(
        self, api_client, staff_header, make_zip, jpeg_factory, archive_settings
    ):
        payload = make_zip({
            'articles/001-b/article.json': b'\xef\xbb\xbf' + article_json(slug='bom-case'),
            'articles/001-b/cover.jpg': jpeg_factory(),
            'articles/001-b/attachment.pdf': b'%PDF',
        })
        report = self._stage_payload(api_client, staff_header, payload).json()['data']
        assert report['items'][0]['action'] == 'create'

    def test_broken_json_reports_line_and_column(
        self, api_client, staff_header, make_zip, jpeg_factory, archive_settings
    ):
        payload = make_zip({
            'articles/001-j/article.json': b'{ "title": "x", }',
            'articles/001-j/cover.jpg': jpeg_factory(),
            'articles/001-j/attachment.pdf': b'%PDF',
        })
        report = self._stage_payload(api_client, staff_header, payload).json()['data']
        assert report['items'][0]['action'] == 'failed'
        assert any('合法 JSON' in e for e in report['items'][0]['errors'])


# --------------------------------------------------------------------------- 并发与限流


class TestConcurrencyAndLimits:
    def _staged_id(self, api_client, staff_header, package):
        return stage(api_client, staff_header, package).json()['data']['staged_id']

    def test_second_commit_is_conflict(self, api_client, staff_header, package, archive_settings):
        staged_id = self._staged_id(api_client, staff_header, package)
        first = api_client.post(
            COMMIT_URL,
            {'staged_id': staged_id, 'strategy': 'skip'},
            content_type='application/json',
            **staff_header,
        )
        assert first.status_code == 200
        second = api_client.post(
            COMMIT_URL,
            {'staged_id': staged_id, 'strategy': 'skip'},
            content_type='application/json',
            **staff_header,
        )
        assert second.status_code == 409

    def test_expired_staging_is_conflict(self, api_client, staff_header, package, archive_settings):
        staged_id = self._staged_id(api_client, staff_header, package)
        ArchiveStaging.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        response = api_client.post(
            COMMIT_URL,
            {'staged_id': staged_id, 'strategy': 'skip'},
            content_type='application/json',
            **staff_header,
        )
        assert response.status_code == 409

    def test_import_lock_conflict(self, api_client, staff_header, package, archive_settings):
        """别人正持锁 → 409（不是静默并发写入）。"""
        from articles.archive.locks import import_lock

        staged_id = self._staged_id(api_client, staff_header, package)
        with import_lock():
            response = api_client.post(
                COMMIT_URL,
                {'staged_id': staged_id, 'strategy': 'skip'},
                content_type='application/json',
                **staff_header,
            )
        assert response.status_code == 409
        assert '导入任务' in response.json()['message']

    def test_min_interval_rate_limit(self, api_client, staff_header, package, settings):
        settings.ARCHIVE_IMPORT_MIN_INTERVAL_SECONDS = 60
        first_id = self._staged_id(api_client, staff_header, package)
        second_id = self._staged_id(api_client, staff_header, package)
        ok = api_client.post(
            COMMIT_URL,
            {'staged_id': first_id, 'strategy': 'skip'},
            content_type='application/json',
            **staff_header,
        )
        assert ok.status_code == 200
        blocked = api_client.post(
            COMMIT_URL,
            {'staged_id': second_id, 'strategy': 'skip'},
            content_type='application/json',
            **staff_header,
        )
        assert blocked.status_code == 429

    def test_rate_limited_commit_does_not_burn_staging(
        self, api_client, staff_header, staff_user, package, settings
    ):
        """被限流（429）时不能消费 staged_id：否则用户得为重传 1GB 包买单。"""
        settings.ARCHIVE_IMPORT_MIN_INTERVAL_SECONDS = 60
        staged_id = self._staged_id(api_client, staff_header, package)
        first = api_client.post(
            COMMIT_URL,
            {'staged_id': staged_id, 'strategy': 'skip'},
            content_type='application/json',
            **staff_header,
        )
        assert first.status_code == 200

        second_id = self._staged_id(api_client, staff_header, package)
        blocked = api_client.post(
            COMMIT_URL,
            {'staged_id': second_id, 'strategy': 'skip'},
            content_type='application/json',
            **staff_header,
        )
        assert blocked.status_code == 429
        assert ArchiveStaging.objects.get(pk=second_id).consumed_at is None

        # 清掉间隔键后，同一个 staged_id 仍可提交（没被烧掉）
        from articles.archive.locks import INTERVAL_KEY

        cache.delete(INTERVAL_KEY.format(user_id=staff_user.id))
        retry = api_client.post(
            COMMIT_URL,
            {'staged_id': second_id, 'strategy': 'skip'},
            content_type='application/json',
            **staff_header,
        )
        assert retry.status_code == 200

    def test_cache_failure_is_fail_closed(
        self, api_client, staff_header, package, archive_settings, monkeypatch
    ):
        """缓存（prod 为 Redis）不可用时必须 503，而不是放行并发导入。"""
        staged_id = self._staged_id(api_client, staff_header, package)

        def _boom(*args, **kwargs):
            raise ConnectionError('redis down')

        monkeypatch.setattr(cache, 'add', _boom)
        response = api_client.post(
            COMMIT_URL,
            {'staged_id': staged_id, 'strategy': 'skip'},
            content_type='application/json',
            **staff_header,
        )
        assert response.status_code == 503

    def test_staging_owner_is_enforced(
        self, api_client, staff_header, package, db, archive_settings
    ):
        """别人的 staged_id 不能被提交（staging 不是能力 URL）。"""
        from django.contrib.auth import get_user_model
        from ninja_jwt.tokens import RefreshToken

        from articles.models import ArchiveStaging as Staging

        staged_id = self._staged_id(api_client, staff_header, package)
        other = get_user_model().objects.create_user(
            username='other-staff', password='x', is_staff=True
        )
        other_header = {
            'HTTP_AUTHORIZATION': f'Bearer {RefreshToken.for_user(other).access_token}'
        }
        response = api_client.post(
            COMMIT_URL,
            {'staged_id': staged_id, 'strategy': 'skip'},
            content_type='application/json',
            **other_header,
        )
        assert response.status_code == 404
        assert Staging.objects.filter(pk=staged_id).exists()

    def test_discard_staging(self, api_client, staff_header, package, archive_settings):
        staged_id = self._staged_id(api_client, staff_header, package)
        response = api_client.delete(
            f'/api/v1/admin/articles/import/stage/{staged_id}/', **staff_header
        )
        assert response.status_code == 200
        assert not ArchiveStaging.objects.filter(pk=staged_id).exists()

    def test_limits_endpoint(self, api_client, staff_header, archive_settings):
        response = api_client.get('/api/v1/admin/articles/import/limits/', **staff_header)
        assert response.status_code == 200
        data = response.json()['data']
        assert data['max_upload_bytes'] > 0
        assert 'pdf' in data['attachment_extensions']
        assert 'html' not in data['attachment_extensions']
        assert 'html' in data['attachment_legacy_extensions']


class TestSweep:
    def test_orphan_staging_dir_is_collected(
        self, api_client, staff_header, package, archive_settings
    ):
        """没有 DB 行的孤儿暂存目录必须被回收（否则永久占盘）。"""
        import os
        import time

        from articles.archive.staging import ensure_subdirs, sweep

        staged_id = stage(api_client, staff_header, package).json()['data']['staged_id']
        path = ensure_subdirs() / 'staging' / staged_id
        assert path.exists()

        # 模拟"行已丢、目录留下"且已陈旧
        ArchiveStaging.objects.filter(pk=staged_id).delete()
        old = time.time() - 7200
        os.utime(path, (old, old))

        removed = sweep()
        assert removed['staging'] >= 1
        assert not path.exists()


def test_zip_writer_used_in_tests_is_readable():
    """自检：测试里造包的方式本身合法（避免测试假阳性）。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as zf:
        zf.writestr('articles/001-a/article.json', b'{}')
    assert zipfile.ZipFile(io.BytesIO(buffer.getvalue())).namelist() == [
        'articles/001-a/article.json'
    ]


def test_article_model_untouched_by_security_tests():
    """护栏：本文件不应留下业务数据。"""
    assert Article.objects.count() == 0
