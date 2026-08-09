"""文章公开接口测试：GET /api/v1/articles/search/。"""
import pytest
from django.utils import timezone

from articles.models import Article


@pytest.mark.django_db
class TestArticleSearchAPI:
    @pytest.fixture
    def setup_articles(self, user):
        Article.objects.create(
            title='我的第一篇博客',
            slug='blog-1',
            content='内容',
            publish_time=timezone.now(),
            author=user,
            is_published=True,
        )
        Article.objects.create(
            title='Python 教程',
            slug='python',
            content='内容',
            publish_time=timezone.now(),
            author=user,
            is_published=True,
        )
        Article.objects.create(
            title='草稿博客',
            slug='draft-blog',
            content='内容',
            publish_time=timezone.now(),
            author=user,
            is_published=False,
        )

    def test_src_001_normal_search(self, api_client, setup_articles):
        """SRC-001 正常搜索返回数组。"""
        response = api_client.get('/api/v1/articles/search/?keyword=博客')

        assert response.status_code == 200
        data = response.json()['data']
        assert len(data) == 1
        assert data[0]['title'] == '我的第一篇博客'

    def test_src_002_no_match(self, api_client, setup_articles):
        """SRC-002 无匹配结果返回空数组。"""
        response = api_client.get('/api/v1/articles/search/?keyword=不存在')

        assert response.status_code == 200
        assert response.json()['data'] == []

    def test_src_003_missing_keyword(self, api_client):
        """SRC-003 缺少 keyword 参数。"""
        response = api_client.get('/api/v1/articles/search/')

        assert response.status_code == 422

    def test_src_004_case_insensitive(self, api_client, setup_articles):
        """SRC-004 大小写不敏感。"""
        response = api_client.get('/api/v1/articles/search/?keyword=python')

        assert response.status_code == 200
        assert len(response.json()['data']) == 1

    def test_src_005_only_published(self, api_client, setup_articles):
        """SRC-005 草稿不参与搜索。"""
        response = api_client.get('/api/v1/articles/search/?keyword=草稿')

        assert response.status_code == 200
        assert response.json()['data'] == []
