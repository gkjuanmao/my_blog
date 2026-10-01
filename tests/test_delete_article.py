"""文章管理接口测试：DELETE /api/v1/admin/articles/{id}/。"""
import os

import pytest
from django.utils import timezone

from articles.models import Article


@pytest.mark.django_db
class TestDeleteArticleAPI:
    @pytest.fixture
    def article(self, user):
        return Article.objects.create(
            title='测试文章',
            slug='test',
            publish_time=timezone.now(),
            author=user,
            is_published=True,
        )

    def test_adm_038_normal_delete(self, api_client, auth_header, article):
        """ADM-038 正常删除（返回 200 信封）。"""
        response = api_client.delete(f'/api/v1/admin/articles/{article.id}/', **auth_header)

        assert response.status_code == 200
        assert not Article.objects.filter(id=article.id).exists()

    def test_adm_039_not_found(self, api_client, auth_header):
        """ADM-039 文章不存在。"""
        response = api_client.delete('/api/v1/admin/articles/9999/', **auth_header)

        assert response.status_code == 404
        assert '不存在' in response.json()['message']

    def test_adm_040_unauthorized(self, api_client, article):
        """ADM-040 未登录删除。"""
        response = api_client.delete(f'/api/v1/admin/articles/{article.id}/')

        assert response.status_code == 401

    def test_adm_041_delete_removes_files(
        self, api_client, auth_header, user, test_image, test_pdf
    ):
        """ADM-041 按 id 删除时同步清理封面与附件文件。"""
        article = Article.objects.create(
            title='带附件文章',
            slug='with-files',
            publish_time=timezone.now(),
            author=user,
            is_published=True,
            cover_image=test_image,
            cover_image_name='test.jpg',
            file=test_pdf,
            file_name='test.pdf',
        )
        cover_path = article.cover_image.path
        file_path = article.file.path
        assert os.path.exists(cover_path)
        assert os.path.exists(file_path)

        response = api_client.delete(f'/api/v1/admin/articles/{article.id}/', **auth_header)

        assert response.status_code == 200
        assert not os.path.exists(cover_path)
        assert not os.path.exists(file_path)

    def test_adm_042_slug_delete_removes_files(
        self, api_client, auth_header, user, test_image, test_pdf
    ):
        """ADM-042 按 slug 删除时同步清理封面与附件文件。"""
        article = Article.objects.create(
            title='按 slug 删除',
            slug='delete-by-slug',
            publish_time=timezone.now(),
            author=user,
            is_published=True,
            cover_image=test_image,
            cover_image_name='test.jpg',
            file=test_pdf,
            file_name='test.pdf',
        )
        cover_path = article.cover_image.path
        file_path = article.file.path

        response = api_client.delete(
            f'/api/v1/admin/articles/slug/{article.slug}/', **auth_header
        )

        assert response.status_code == 200
        assert not os.path.exists(cover_path)
        assert not os.path.exists(file_path)

    def test_adm_043_queryset_delete_removes_files(
        self, user, test_image, test_pdf, media_root
    ):
        """ADM-043 QuerySet.delete()（admin 批量删除路径）同样触发文件清理。"""
        article = Article.objects.create(
            title='批量删除',
            slug='bulk-delete',
            publish_time=timezone.now(),
            author=user,
            is_published=True,
            cover_image=test_image,
            cover_image_name='test.jpg',
            file=test_pdf,
            file_name='test.pdf',
        )
        cover_path = article.cover_image.path
        file_path = article.file.path

        Article.objects.filter(pk=article.pk).delete()

        assert not os.path.exists(cover_path)
        assert not os.path.exists(file_path)


@pytest.mark.django_db
class TestBulkDeleteAPI:
    """POST /api/v1/admin/articles/bulk-delete/（批量删除）。"""

    URL = '/api/v1/admin/articles/bulk-delete/'

    def _make(self, user, slug, test_image, test_pdf):
        return Article.objects.create(
            title=f'批量文章 {slug}',
            slug=slug,
            publish_time=timezone.now(),
            author=user,
            is_published=True,
            cover_image=test_image,
            cover_image_name='test.jpg',
            file=test_pdf,
            file_name='test.pdf',
        )

    def test_bulk_046_deletes_multiple_and_cleans_files(
        self, api_client, auth_header, user, test_image, test_pdf
    ):
        """ADM-046 批量删除多篇，并同步清理各自的封面/附件。"""
        first = self._make(user, 'bulk-a', test_image, test_pdf)
        second = self._make(user, 'bulk-b', test_image, test_pdf)
        paths = [first.cover_image.path, first.file.path, second.cover_image.path, second.file.path]
        assert all(os.path.exists(path) for path in paths)

        response = api_client.post(
            self.URL,
            {'ids': [first.id, second.id]},
            content_type='application/json',
            **auth_header,
        )

        assert response.status_code == 200
        data = response.json()['data']
        assert data == {'requested': 2, 'deleted': 2, 'not_found': []}
        assert Article.objects.count() == 0
        assert not any(os.path.exists(path) for path in paths)

    def test_bulk_047_reports_missing_ids(
        self, api_client, auth_header, user, test_image, test_pdf
    ):
        """ADM-047 不存在的 id 不算错误，单独回显（幂等友好）。"""
        article = self._make(user, 'bulk-c', test_image, test_pdf)

        response = api_client.post(
            self.URL,
            {'ids': [article.id, 999999]},
            content_type='application/json',
            **auth_header,
        )

        assert response.status_code == 200
        data = response.json()['data']
        assert data['deleted'] == 1
        assert data['not_found'] == [999999]

    def test_bulk_048_deduplicates_ids(self, api_client, auth_header, user, test_image, test_pdf):
        """ADM-048 重复 id 去重后计数。"""
        article = self._make(user, 'bulk-d', test_image, test_pdf)

        response = api_client.post(
            self.URL,
            {'ids': [article.id, article.id]},
            content_type='application/json',
            **auth_header,
        )

        assert response.json()['data'] == {'requested': 1, 'deleted': 1, 'not_found': []}

    def test_bulk_049_empty_ids(self, api_client, auth_header):
        """ADM-049 空 ids → 400。"""
        response = api_client.post(
            self.URL, {'ids': []}, content_type='application/json', **auth_header
        )
        assert response.status_code == 400
        assert '不能为空' in response.json()['message']

    def test_bulk_050_over_cap(
        self, api_client, auth_header, user, test_image, test_pdf, monkeypatch
    ):
        """ADM-050 超过单次上限 → 400。"""
        import articles.api as api_module

        monkeypatch.setattr(api_module, 'BULK_DELETE_MAX_IDS', 1)
        article = self._make(user, 'bulk-e', test_image, test_pdf)

        response = api_client.post(
            self.URL,
            {'ids': [article.id, 999999]},
            content_type='application/json',
            **auth_header,
        )
        assert response.status_code == 400
        assert '最多删除 1 篇' in response.json()['message']

    def test_bulk_051_unauthorized(self, api_client):
        """ADM-051 未登录 → 401。"""
        response = api_client.post(
            self.URL, {'ids': [1]}, content_type='application/json'
        )
        assert response.status_code == 401

    def test_bulk_052_route_not_shadowed_by_detail_route(self, api_client, auth_header):
        """ADM-052 回归防护：该路径曾被 /articles/{article_id}/ 拦成 405。"""
        response = api_client.post(
            self.URL, {'ids': [999999]}, content_type='application/json', **auth_header
        )
        assert response.status_code != 405
        assert response.status_code == 200
