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
