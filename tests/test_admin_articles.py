"""文章管理接口测试：GET /api/v1/admin/articles/（列表）与按 slug 删除。"""
import pytest
from django.utils import timezone

from articles.models import Article, Category


@pytest.mark.django_db
class TestAdminArticleListAPI:
    @pytest.fixture
    def setup_articles(self, user):
        category = Category.objects.create(name='技术', slug='tech')
        Article.objects.create(
            title='已发布文章', slug='published',
            publish_time=timezone.now(), author=user, category=category, is_published=True,
        )
        Article.objects.create(
            title='草稿文章', slug='draft-post',
            publish_time=timezone.now(), author=user, category=category, is_published=False,
        )

    def test_adm_041_list_all_including_draft(self, api_client, auth_header, setup_articles):
        """ADM-041 管理列表返回全部文章（含草稿）。"""
        response = api_client.get('/api/v1/admin/articles/', **auth_header)

        assert response.status_code == 200
        data = response.json()['data']
        assert data['total'] == 2
        slugs = [item['slug'] for item in data['items']]
        assert 'draft-post' in slugs

    def test_adm_042_unauthorized(self, api_client):
        """ADM-042 未登录访问管理列表。"""
        response = api_client.get('/api/v1/admin/articles/')

        assert response.status_code == 401

    def test_adm_043_filter_unpublished(self, api_client, auth_header, setup_articles):
        """ADM-043 is_published=false 只返回草稿。"""
        response = api_client.get('/api/v1/admin/articles/?is_published=false', **auth_header)

        assert response.status_code == 200
        data = response.json()['data']
        assert data['total'] == 1
        assert data['items'][0]['slug'] == 'draft-post'

    def test_adm_044_keyword_search(self, api_client, auth_header, setup_articles):
        """ADM-044 按标题关键词搜索。"""
        response = api_client.get('/api/v1/admin/articles/?keyword=草稿', **auth_header)

        assert response.status_code == 200
        data = response.json()['data']
        assert data['total'] == 1
        assert data['items'][0]['slug'] == 'draft-post'

    def test_adm_045_category_filter(self, api_client, auth_header, setup_articles):
        """ADM-045 按 category_slug 过滤。"""
        response = api_client.get('/api/v1/admin/articles/?category_slug=tech', **auth_header)

        assert response.status_code == 200
        assert response.json()['data']['total'] == 2

    def test_adm_046_pagination(self, api_client, auth_header, setup_articles):
        """ADM-046 管理列表分页。"""
        response = api_client.get('/api/v1/admin/articles/?page_size=1', **auth_header)

        assert response.status_code == 200
        data = response.json()['data']
        assert len(data['items']) == 1
        assert data['total'] == 2
        assert data['page_size'] == 1

    @pytest.fixture
    def ordered_articles(self, user):
        """三篇发布时间递增的文章，用于排序断言。"""
        category = Category.objects.create(name='排序分类', slug='order-cat')
        base = timezone.now()
        for index, title in enumerate(['最早发布', '居中发布', '最新发布']):
            Article.objects.create(
                title=title,
                slug=f'order-{index}',
                publish_time=base + timezone.timedelta(days=index),
                author=user,
                category=category,
                is_published=True,
                views=index * 10,
            )

    def test_adm_056_ordering_asc(self, api_client, auth_header, ordered_articles):
        """ADM-056 ordering=publish_time 按发布时间升序。"""
        response = api_client.get(
            '/api/v1/admin/articles/?ordering=publish_time', **auth_header
        )

        assert response.status_code == 200
        titles = [item['title'] for item in response.json()['data']['items']]
        assert titles == ['最早发布', '居中发布', '最新发布']

    def test_adm_057_ordering_desc(self, api_client, auth_header, ordered_articles):
        """ADM-057 ordering=-publish_time 按发布时间降序。"""
        response = api_client.get(
            '/api/v1/admin/articles/?ordering=-publish_time', **auth_header
        )

        assert response.status_code == 200
        titles = [item['title'] for item in response.json()['data']['items']]
        assert titles == ['最新发布', '居中发布', '最早发布']

    def test_adm_058_ordering_allowlist(self, api_client, auth_header, ordered_articles):
        """ADM-058 非白名单排序字段返回 400（防任意字段注入）。"""
        response = api_client.get('/api/v1/admin/articles/?ordering=password', **auth_header)

        assert response.status_code == 400
        assert '排序' in response.json()['message']

    def test_adm_059_ordering_with_filter(self, api_client, auth_header, ordered_articles):
        """ADM-059 排序与状态过滤可组合。"""
        Article.objects.filter(slug='order-1').update(is_published=False)

        response = api_client.get(
            '/api/v1/admin/articles/?is_published=true&ordering=-publish_time', **auth_header
        )

        assert response.status_code == 200
        titles = [item['title'] for item in response.json()['data']['items']]
        assert titles == ['最新发布', '最早发布']


@pytest.mark.django_db
class TestAdminDeleteBySlugAPI:
    @pytest.fixture
    def draft(self, user):
        return Article.objects.create(
            title='草稿文章', slug='draft-post',
            publish_time=timezone.now(), author=user, is_published=False,
        )

    def test_adm_047_delete_draft_by_slug(self, api_client, auth_header, draft):
        """ADM-047 按 slug 删除未发布草稿。"""
        response = api_client.delete('/api/v1/admin/articles/slug/draft-post/', **auth_header)

        assert response.status_code == 200
        assert not Article.objects.filter(slug='draft-post').exists()

    def test_adm_048_slug_not_found(self, api_client, auth_header):
        """ADM-048 slug 不存在。"""
        response = api_client.delete('/api/v1/admin/articles/slug/not-exist/', **auth_header)

        assert response.status_code == 404
        assert '不存在' in response.json()['message']

    def test_adm_049_unauthorized(self, api_client, draft):
        """ADM-049 未登录按 slug 删除。"""
        response = api_client.delete('/api/v1/admin/articles/slug/draft-post/')

        assert response.status_code == 401
