"""文章公开接口测试：GET /api/v1/tags/。"""
import pytest

from articles.models import Tag


@pytest.mark.django_db
class TestTagsAPI:
    def test_tag_001_get_tags(self, api_client):
        """TAG-001 正常获取标签列表。"""
        Tag.objects.create(name='Python', slug='python')
        Tag.objects.create(name='旅行', slug='travel')

        response = api_client.get('/api/v1/tags/')

        assert response.status_code == 200
        data = response.json()['data']
        assert len(data) == 2
        assert {item['slug'] for item in data} == {'python', 'travel'}

    def test_tag_002_empty_tags(self, api_client):
        """TAG-002 无标签数据返回空数组。"""
        response = api_client.get('/api/v1/tags/')

        assert response.status_code == 200
        assert response.json()['data'] == []
