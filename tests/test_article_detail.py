"""文章公开接口测试：GET /api/v1/articles/{slug}/。"""
import pytest
from django.utils import timezone

from articles.models import Article


@pytest.mark.django_db
class TestArticleDetailAPI:
    @pytest.fixture
    def article(self, user):
        return Article.objects.create(
            title='测试文章',
            slug='my-post',
            publish_time=timezone.now(),
            author=user,
            is_published=True,
            views=10,
        )

    def test_art_015_get_detail(self, api_client, article):
        """ART-015 正常获取详情。"""
        response = api_client.get('/api/v1/articles/my-post/')

        assert response.status_code == 200
        data = response.json()['data']
        assert data['title'] == '测试文章'
        assert data['slug'] == 'my-post'

    def test_art_016_not_found(self, api_client):
        """ART-016 文章不存在。"""
        response = api_client.get('/api/v1/articles/not-exist/')

        assert response.status_code == 404
        assert '不存在' in response.json()['message']

    def test_art_017_unpublished(self, api_client, user):
        """ART-017 未发布文章对外不可见。"""
        Article.objects.create(
            title='草稿',
            slug='draft',
            publish_time=timezone.now(),
            author=user,
            is_published=False,
        )

        response = api_client.get('/api/v1/articles/draft/')

        assert response.status_code == 404

    def test_art_018_views_increment(self, api_client, article):
        """ART-018 阅读量 +1。"""
        response = api_client.get('/api/v1/articles/my-post/')

        assert response.status_code == 200
        article.refresh_from_db()
        assert article.views == 11

    def test_art_019_views_dedup_same_ip(self, api_client, article):
        """ART-019 同一 IP 在去重窗口内重复访问不重复计数。"""
        api_client.get('/api/v1/articles/my-post/', HTTP_X_FORWARDED_FOR='10.0.0.1')
        second = api_client.get('/api/v1/articles/my-post/', HTTP_X_FORWARDED_FOR='10.0.0.1')

        assert second.status_code == 200
        article.refresh_from_db()
        assert article.views == 11

    def test_art_020_views_counted_per_ip(self, api_client, article):
        """ART-020 不同 IP 各自计一次。"""
        api_client.get('/api/v1/articles/my-post/', HTTP_X_FORWARDED_FOR='10.0.0.2')
        api_client.get('/api/v1/articles/my-post/', HTTP_X_FORWARDED_FOR='10.0.0.3')

        article.refresh_from_db()
        assert article.views == 12
