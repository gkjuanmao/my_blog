"""文章公开接口测试：GET /api/v1/articles/（分页）。"""
import pytest
from django.utils import timezone

from articles.models import Article, Category, Tag


@pytest.mark.django_db
class TestArticleListAPI:
    @pytest.fixture
    def setup_articles(self, user):
        """创建 15 篇已发布文章与 1 篇草稿，部分文章挂标签。"""
        category = Category.objects.create(name='技术', slug='tech')
        travel = Tag.objects.create(name='旅行', slug='travel')
        food = Tag.objects.create(name='美食', slug='food')
        for i in range(15):
            article = Article.objects.create(
                title=f'文章{i}',
                slug=f'article-{i}',
                publish_time=timezone.now(),
                author=user,
                category=category,
                is_published=True,
            )
            if i < 5:
                article.tags.add(travel)
            elif i < 8:
                article.tags.add(food)
        Article.objects.create(
            title='草稿',
            slug='draft',
            publish_time=timezone.now(),
            author=user,
            is_published=False,
        )

    def test_art_001_default_pagination(self, api_client, setup_articles):
        """ART-001 默认分页：第 1 页 10 条。"""
        response = api_client.get('/api/v1/articles/')

        assert response.status_code == 200
        data = response.json()['data']
        assert len(data['items']) == 10
        assert data['total'] == 15
        assert data['page'] == 1

    def test_art_002_page_2(self, api_client, setup_articles):
        """ART-002 第 2 页返回 5 条。"""
        response = api_client.get('/api/v1/articles/?page=2')

        assert response.status_code == 200
        data = response.json()['data']
        assert len(data['items']) == 5

    def test_art_003_custom_page_size(self, api_client, setup_articles):
        """ART-003 自定义 page_size=5。"""
        response = api_client.get('/api/v1/articles/?page_size=5')

        assert response.status_code == 200
        assert len(response.json()['data']['items']) == 5

    def test_art_004_invalid_page(self, api_client):
        """ART-004 非法 page=0。"""
        response = api_client.get('/api/v1/articles/?page=0')

        assert response.status_code == 422

    def test_art_005_only_published(self, api_client, setup_articles):
        """ART-005 草稿不出现在列表中。"""
        response = api_client.get('/api/v1/articles/')

        data = response.json()['data']
        slugs = [item['slug'] for item in data['items']]
        assert 'draft' not in slugs

    def test_art_006_filter_by_category(self, api_client, setup_articles):
        """ART-006 按 category_slug 过滤。"""
        response = api_client.get('/api/v1/articles/?category_slug=tech')

        assert response.status_code == 200
        assert response.json()['data']['total'] == 15

    def test_art_007_empty_database(self, api_client):
        """ART-007 空数据库。"""
        response = api_client.get('/api/v1/articles/')

        assert response.status_code == 200
        data = response.json()['data']
        assert data['items'] == []
        assert data['total'] == 0

    def test_art_008_filter_by_tag(self, api_client, setup_articles):
        """ART-008 按 tag_slug 过滤。"""
        response = api_client.get('/api/v1/articles/?tag_slug=travel')

        assert response.status_code == 200
        data = response.json()['data']
        assert data['total'] == 5
        assert all(
            any(t['slug'] == 'travel' for t in item['tags'])
            for item in data['items']
        )

    def test_art_009_filter_by_tag_no_hit(self, api_client, setup_articles):
        """ART-009 tag_slug 无命中。"""
        response = api_client.get('/api/v1/articles/?tag_slug=no-such')

        assert response.status_code == 200
        data = response.json()['data']
        assert data['items'] == []
        assert data['total'] == 0

    def test_art_010_filter_by_category_and_tag(self, api_client, setup_articles):
        """ART-010 category_slug + tag_slug 组合过滤。"""
        response = api_client.get('/api/v1/articles/?category_slug=tech&tag_slug=travel')

        assert response.status_code == 200
        assert response.json()['data']['total'] == 5
