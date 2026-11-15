"""文章公开统计接口测试：GET /api/v1/articles/stats/（分类 / 标签篇数聚合）。"""
import pytest
from django.utils import timezone

from articles.models import Article, Category, Tag


@pytest.mark.django_db
class TestArticleStatsAPI:
    @pytest.fixture
    def setup_articles(self, user):
        """两个分类、两个标签、15 篇已发布 + 2 篇草稿。"""
        tech = Category.objects.create(name='技术', slug='tech')
        life = Category.objects.create(name='生活', slug='life')
        travel = Tag.objects.create(name='旅行', slug='travel')
        food = Tag.objects.create(name='美食', slug='food')

        for i in range(10):
            article = Article.objects.create(
                title=f'技术文{i}',
                slug=f'tech-{i}',
                publish_time=timezone.now(),
                author=user,
                category=tech,
                is_published=True,
            )
            if i < 4:
                article.tags.add(travel)
        for i in range(5):
            article = Article.objects.create(
                title=f'生活文{i}',
                slug=f'life-{i}',
                publish_time=timezone.now(),
                author=user,
                category=life,
                is_published=True,
            )
            if i < 2:
                article.tags.add(food)

        # 草稿不该进任何计数（含 total）
        Article.objects.create(
            title='草稿技术',
            slug='draft-tech',
            publish_time=timezone.now(),
            author=user,
            category=tech,
            is_published=False,
        )
        Article.objects.create(
            title='草稿无分类',
            slug='draft-none',
            publish_time=timezone.now(),
            author=user,
            is_published=False,
        )

    def test_stat_001_counts_published_only(self, api_client, setup_articles):
        """STAT-001 只统计已发布文章，草稿不计入 total 与各分组。"""
        response = api_client.get('/api/v1/articles/stats/')

        assert response.status_code == 200
        data = response.json()['data']
        assert data['total'] == 15
        assert data['by_category'] == {'tech': 10, 'life': 5}
        assert data['by_tag'] == {'travel': 4, 'food': 2}

    def test_stat_002_empty_database(self, api_client):
        """STAT-002 空站：total 为 0，两个分组为空字典（不是 null）。"""
        response = api_client.get('/api/v1/articles/stats/')

        assert response.status_code == 200
        data = response.json()['data']
        assert data['total'] == 0
        assert data['by_category'] == {}
        assert data['by_tag'] == {}

    def test_stat_003_category_totals_match_list_filter(self, api_client, setup_articles):
        """STAT-003 口径一致性：stats 里某分类的数量 == 列表接口按该分类过滤的 total。"""
        stats = api_client.get('/api/v1/articles/stats/').json()['data']
        listed = api_client.get('/api/v1/articles/?category_slug=tech').json()['data']

        assert stats['by_category']['tech'] == listed['total']
