"""归档导出、票据下载与路由顺序测试。"""
import hashlib
import io
import json
import zipfile
from datetime import timedelta

import pytest
from django.urls import resolve
from django.utils import timezone

from articles.models import ArchiveTicket

pytestmark = pytest.mark.django_db

EXPORT_URL = '/api/v1/admin/articles/export/'
ESTIMATE_URL = '/api/v1/admin/articles/export/estimate/'


@pytest.fixture
def article(article_factory, staff_user, jpeg_factory):
    """一篇带真实封面/附件的文章。"""
    return article_factory(staff_user, cover_bytes=jpeg_factory())


# --------------------------------------------------------------------------- 路由顺序


class TestArchiveRouting:
    """钉住路由顺序：/articles/export/ 必须早于 /articles/{article_id}/。

    不断言视图函数名（django-ninja 会把路径包成自己的 wrapper），而是断言解析出的
    **路径参数**：一旦顺序错了，'export' 会被当成 article_id。
    """

    @pytest.mark.parametrize(
        'path',
        [
            '/api/v1/admin/articles/export/',
            '/api/v1/admin/articles/export/estimate/',
            '/api/v1/admin/articles/import/stage/',
            '/api/v1/admin/articles/import/commit/',
            '/api/v1/admin/articles/import/limits/',
        ],
    )
    def test_archive_paths_have_no_article_id(self, path):
        match = resolve(path)
        assert 'article_id' not in match.kwargs

    def test_ticket_path_carries_only_ticket(self):
        match = resolve('/api/v1/admin/archives/11111111-1111-1111-1111-111111111111/')
        assert set(match.kwargs) == {'ticket'}

    def test_detail_route_still_works(self):
        match = resolve('/api/v1/admin/articles/7/')
        assert match.kwargs.get('article_id') == '7'

    def test_export_path_not_captured_by_detail_route(self):
        """回归防护：详情路由没有 int 转换器，会把 'export' 当 article_id。"""
        match = resolve(EXPORT_URL)
        assert 'article_id' not in match.kwargs


# --------------------------------------------------------------------------- 权限


class TestExportPermissions:
    def test_requires_staff(self, api_client, auth_header, article):
        """非 staff 的登录用户不能导出（否则可拿走全部草稿）。"""
        response = api_client.get(EXPORT_URL, **auth_header)
        assert response.status_code == 403

    def test_anonymous_rejected(self, api_client):
        response = api_client.get(EXPORT_URL)
        assert response.status_code == 401


# --------------------------------------------------------------------------- 导出与下载


class TestExportFlow:
    def test_export_then_download(self, api_client, staff_header, article, zip_bytes):
        response = api_client.get(f'{EXPORT_URL}?ids={article.id}', **staff_header)
        assert response.status_code == 200, response.json()
        data = response.json()['data']
        assert data['count'] == 1
        assert data['filename'].startswith('articles-')
        assert data['filename'].endswith('.zip')

        download = api_client.get(data['download_url'])
        assert download.status_code == 200
        assert download['Content-Disposition'].startswith('attachment')
        assert download['Content-Type'] == 'application/zip'

        with zipfile.ZipFile(io.BytesIO(zip_bytes(download))) as zf:
            names = zf.namelist()
            assert 'manifest.json' in names
            assert 'README.md' in names
            article_entries = [n for n in names if n.endswith('/article.json')]
            assert len(article_entries) == 1
            base = article_entries[0].rsplit('/', 1)[0]
            assert base.startswith('articles/001-')
            assert f'{base}/cover.webp' in names
            assert f'{base}/attachment.pdf' in names

            payload = json.loads(zf.read(article_entries[0]))
            assert payload['title'] == '示例游记'
            assert payload['slug'] == article.slug
            assert payload['cover']['file'] == 'cover.webp'
            assert payload['cover']['sha256'] == hashlib.sha256(
                zf.read(f'{base}/cover.webp')
            ).hexdigest()
            assert payload['import']['action'] == 'auto'
            assert payload['content'] == article.content
            assert payload['images'] == []

            manifest = json.loads(zf.read('manifest.json'))
            assert manifest['schema'] == 'myblog.archive/v2'
            assert manifest['ignored_on_import'] == ['views', 'created_at', 'updated_at']
            assert manifest['articles'][0]['slug'] == article.slug

    def test_export_estimate_reports_importable(self, api_client, staff_header, article):
        response = api_client.get(f'{ESTIMATE_URL}?ids={article.id}', **staff_header)
        assert response.status_code == 200
        data = response.json()['data']
        assert data['count'] == 1
        # 固定成员 manifest.json + README.md，加上每篇的 article.json + 封面 + 附件
        assert data['entries'] == 5
        assert data['importable'] is True
        assert data['blocking_reasons'] == []

    def test_export_empty_selection(self, api_client, staff_header):
        response = api_client.get(EXPORT_URL, **staff_header)
        assert response.status_code == 400
        assert '没有符合条件' in response.json()['message']

    def test_export_drafts_by_filter(
        self, api_client, staff_header, staff_user, jpeg_factory, article_factory, zip_bytes
    ):
        draft = article_factory(
            staff_user,
            slug='draft-one',
            title='草稿',
            published=False,
            cover_bytes=jpeg_factory(),
        )
        response = api_client.get(f'{EXPORT_URL}?is_published=false', **staff_header)
        assert response.status_code == 200
        assert response.json()['data']['count'] == 1

        download = api_client.get(response.json()['data']['download_url'])
        with zipfile.ZipFile(io.BytesIO(zip_bytes(download))) as zf:
            base = [n for n in zf.namelist() if n.endswith('/article.json')][0].rsplit('/', 1)[0]
            payload = json.loads(zf.read(f'{base}/article.json'))
            assert payload['slug'] == draft.slug
            assert payload['is_published'] is False

    def test_export_media_bytes_are_untouched(self, api_client, staff_header, article, zip_bytes):
        """导出不做重编码：包内封面字节与库内文件逐字节一致。"""
        data = api_client.get(f'{EXPORT_URL}?ids={article.id}', **staff_header).json()['data']
        with zipfile.ZipFile(io.BytesIO(zip_bytes(api_client.get(data['download_url'])))) as zf:
            entry = [n for n in zf.namelist() if n.endswith('cover.webp')][0]
            packed = zf.read(entry)
        with article.cover_image.open('rb') as handle:
            assert handle.read() == packed


# --------------------------------------------------------------------------- 上限（可回导性）


class TestExportLimits:
    def test_ids_limit(self, api_client, staff_header, article, settings):
        settings.ARCHIVE_MAX_IDS_PER_REQUEST = 1
        response = api_client.get(
            f'{EXPORT_URL}?ids={article.id},{article.id + 1}', **staff_header
        )
        assert response.status_code == 400
        assert 'ids 数量超过上限' in response.json()['message']

    def test_rejects_package_that_cannot_be_imported(
        self, api_client, staff_header, staff_user, jpeg_factory, article_factory, settings
    ):
        """B1：导出上限必须受导入上限约束，否则产出自己导不回的包。"""
        settings.ARCHIVE_MAX_ENTRIES = 3  # 2 篇需要 6 个条目
        for index in (1, 2):
            article_factory(
                staff_user,
                slug=f'many-{index}',
                title=f'游记{index}',
                cover_bytes=jpeg_factory(),
            )
        response = api_client.get(EXPORT_URL, **staff_header)
        assert response.status_code == 400
        assert '超过导入上限' in response.json()['message']

        estimate = api_client.get(ESTIMATE_URL, **staff_header).json()['data']
        assert estimate['importable'] is False
        assert estimate['blocking_reasons']

    def test_export_warns_when_media_missing(
        self, api_client, staff_header, staff_user, jpeg_factory, article_factory
    ):
        article = article_factory(staff_user, slug='no-file', cover_bytes=jpeg_factory())
        article.file.storage.delete(article.file.name)  # 磁盘上删掉附件
        response = api_client.get(f'{EXPORT_URL}?ids={article.id}', **staff_header)
        assert response.status_code == 200
        assert any('磁盘上缺失' in w for w in response.json()['data']['warnings'])


# --------------------------------------------------------------------------- 票据生命周期


class TestTicketLifecycle:
    def _issue(self, api_client, staff_header, article):
        data = api_client.get(f'{EXPORT_URL}?ids={article.id}', **staff_header).json()['data']
        return data['download_url']

    def test_single_use(self, api_client, staff_header, article):
        url = self._issue(api_client, staff_header, article)
        assert api_client.get(url).status_code == 200
        second = api_client.get(url)
        assert second.status_code == 410
        assert '已使用或已过期' in second.json()['message']

    def test_expired(self, api_client, staff_header, article):
        url = self._issue(api_client, staff_header, article)
        ArchiveTicket.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        assert api_client.get(url).status_code == 410

    def test_reissue_after_use(self, api_client, staff_header, article):
        url = self._issue(api_client, staff_header, article)
        assert api_client.get(url).status_code == 200
        ticket_id = url.rstrip('/').rsplit('/', 1)[-1]

        reissued = api_client.post(
            f'/api/v1/admin/archives/{ticket_id}/reissue/', **staff_header
        )
        assert reissued.status_code == 200
        assert api_client.get(reissued.json()['data']['download_url']).status_code == 200

    def test_reissue_requires_staff(self, api_client, staff_header, article, auth_header):
        url = self._issue(api_client, staff_header, article)
        ticket_id = url.rstrip('/').rsplit('/', 1)[-1]
        response = api_client.post(
            f'/api/v1/admin/archives/{ticket_id}/reissue/', **auth_header
        )
        assert response.status_code == 403

    def test_unknown_ticket_is_404(self, api_client):
        response = api_client.get('/api/v1/admin/archives/not-a-uuid/')
        assert response.status_code == 404

    def test_missing_file_returns_400(self, api_client, staff_header, article):
        url = self._issue(api_client, staff_header, article)
        from articles.archive.staging import archive_root

        for path in (archive_root() / 'exports').glob('*.zip'):
            path.unlink()
        response = api_client.get(url)
        assert response.status_code == 400
        assert '已过期或被清理' in response.json()['message']
