"""文章公开接口测试：GET /api/v1/categories/。"""
import pytest

from articles.models import Category


@pytest.mark.django_db
class TestCategoriesAPI:
    def test_cat_001_get_categories(self, api_client):
        """CAT-001 正常获取分类列表。"""
        Category.objects.create(name='技术', slug='tech')
        Category.objects.create(name='生活', slug='life')

        response = api_client.get('/api/v1/categories/')

        assert response.status_code == 200
        data = response.json()['data']
        assert len(data) == 2

    def test_cat_002_empty_categories(self, api_client):
        """CAT-002 无分类数据。"""
        response = api_client.get('/api/v1/categories/')

        assert response.status_code == 200
        assert response.json()['data'] == []
