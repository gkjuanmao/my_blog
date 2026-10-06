"""公开列表接口的短 TTL 缓存与 Cache-Control 响应头。"""
import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from articles.models import Article, Category, Tag


@pytest.fixture
def published_article(user):
    return Article.objects.create(
        title='缓存文章',
        slug='cached-post',
        publish_time=timezone.now(),
        author=user,
        is_published=True,
    )


@pytest.mark.django_db
class TestPublicListCache:
    def test_articles_second_request_hits_cache(self, api_client, published_article):
        """第二次请求命中缓存，不再查库。"""
        api_client.get('/api/v1/articles/')
        with CaptureQueriesContext(connection) as ctx:
            response = api_client.get('/api/v1/articles/')

        assert response.status_code == 200
        assert len(ctx.captured_queries) == 0

    def test_categories_second_request_hits_cache(self, api_client):
        Category.objects.create(name='技术', slug='tech')
        api_client.get('/api/v1/categories/')
        with CaptureQueriesContext(connection) as ctx:
            response = api_client.get('/api/v1/categories/')

        assert response.status_code == 200
        assert len(ctx.captured_queries) == 0

    def test_write_invalidates_cache(self, api_client, published_article, user):
        """新建文章后缓存失效，列表立即可见。"""
        first = api_client.get('/api/v1/articles/').json()['data']
        assert first['total'] == 1

        Article.objects.create(
            title='新文章',
            slug='brand-new',
            publish_time=timezone.now(),
            author=user,
            is_published=True,
        )

        second = api_client.get('/api/v1/articles/').json()['data']
        assert second['total'] == 2

    def test_category_write_invalidates_cache(self, api_client):
        Category.objects.create(name='技术', slug='tech')
        assert len(api_client.get('/api/v1/categories/').json()['data']) == 1

        Category.objects.create(name='生活', slug='life')
        assert len(api_client.get('/api/v1/categories/').json()['data']) == 2

    def test_tag_write_invalidates_cache(self, api_client):
        Tag.objects.create(name='Python', slug='python')
        assert len(api_client.get('/api/v1/tags/').json()['data']) == 1

        Tag.objects.create(name='旅行', slug='travel')
        assert len(api_client.get('/api/v1/tags/').json()['data']) == 2


@pytest.mark.django_db
class TestPublicCacheControlHeader:
    def test_public_list_sets_cache_control(self, api_client, published_article):
        response = api_client.get('/api/v1/articles/')
        assert response['Cache-Control'] == 'public, max-age=60'

    def test_categories_sets_cache_control(self, api_client):
        assert api_client.get('/api/v1/categories/')['Cache-Control'] == 'public, max-age=60'
        assert api_client.get('/api/v1/tags/')['Cache-Control'] == 'public, max-age=60'

    def test_article_detail_not_public_cached(self, api_client, published_article):
        """详情会写阅读量，不能被公共缓存。"""
        response = api_client.get('/api/v1/articles/cached-post/')
        assert 'public' not in response.get('Cache-Control', '')

    def test_admin_list_not_public_cached(self, api_client, staff_header, published_article):
        response = api_client.get('/api/v1/admin/articles/', **staff_header)
        assert 'public' not in response.get('Cache-Control', '')
