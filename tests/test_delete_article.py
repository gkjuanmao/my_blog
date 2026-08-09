"""文章管理接口测试：DELETE /api/v1/admin/articles/{id}/。"""
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
            content='内容',
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
