"""文章公开接口测试：GET /api/v1/articles/search/。"""
import pytest
from django.utils import timezone

from articles.models import Article


@pytest.mark.django_db
class TestArticleSearchAPI:
    @pytest.fixture
    def setup_articles(self, user):
        for index in range(3):
            Article.objects.create(
                title=f'我的第{index}篇博客',
                slug=f'blog-{index}',
                publish_time=timezone.now(),
                author=user,
                is_published=True,
            )
        Article.objects.create(
            title='Python 教程',
            slug='python',
            publish_time=timezone.now(),
            author=user,
            is_published=True,
        )
        Article.objects.create(
            title='草稿博客',
            slug='draft-blog',
            publish_time=timezone.now(),
            author=user,
            is_published=False,
        )

    def test_src_001_normal_search(self, api_client, setup_articles):
        """SRC-001 正常搜索返回分页信封。"""
        response = api_client.get('/api/v1/articles/search/?keyword=Python')

        assert response.status_code == 200
        data = response.json()['data']
        assert data['total'] == 1
        assert data['page'] == 1
        assert data['page_size'] == 10
        assert len(data['items']) == 1
        assert data['items'][0]['title'] == 'Python 教程'

    def test_src_002_no_match(self, api_client, setup_articles):
        """SRC-002 无匹配结果返回空 items + total=0。"""
        response = api_client.get('/api/v1/articles/search/?keyword=不存在')

        assert response.status_code == 200
        data = response.json()['data']
        assert data['items'] == []
        assert data['total'] == 0

    def test_src_003_missing_keyword(self, api_client):
        """SRC-003 缺少 keyword 参数。"""
        response = api_client.get('/api/v1/articles/search/')

        assert response.status_code == 422

    def test_src_004_case_insensitive(self, api_client, setup_articles):
        """SRC-004 大小写不敏感。"""
        response = api_client.get('/api/v1/articles/search/?keyword=python')

        assert response.status_code == 200
        assert response.json()['data']['total'] == 1

    def test_src_005_only_published(self, api_client, setup_articles):
        """SRC-005 草稿不参与搜索。"""
        response = api_client.get('/api/v1/articles/search/?keyword=草稿')

        assert response.status_code == 200
        assert response.json()['data']['items'] == []

    def test_src_006_pagination(self, api_client, setup_articles):
        """SRC-006 分页：total 为命中总数，items 按每页数量截断。"""
        response = api_client.get('/api/v1/articles/search/?keyword=博客&page=1&page_size=2')

        assert response.status_code == 200
        data = response.json()['data']
        assert data['total'] == 3
        assert len(data['items']) == 2
        assert data['page'] == 1
        assert data['page_size'] == 2

        second = api_client.get('/api/v1/articles/search/?keyword=博客&page=2&page_size=2')
        assert len(second.json()['data']['items']) == 1

    def test_src_007_invalid_page_size(self, api_client, setup_articles):
        """SRC-007 page_size 超过上限返回 422。"""
        response = api_client.get('/api/v1/articles/search/?keyword=博客&page_size=101')

        assert response.status_code == 422
