"""管理端单篇文章接口测试：GET /api/v1/admin/articles/{id}/。"""
import pytest
from django.utils import timezone

from articles.models import Article, Category


@pytest.mark.django_db
class TestAdminArticleDetailAPI:
    @pytest.fixture
    def setup_articles(self, user):
        category = Category.objects.create(name='技术', slug='tech')
        published = Article.objects.create(
            title='已发布文章', slug='published',
            publish_time=timezone.now(), author=user, category=category, is_published=True,
        )
        draft = Article.objects.create(
            title='草稿文章', slug='draft-post',
            publish_time=timezone.now(), author=user, category=category, is_published=False,
        )
        return published, draft

    def test_adm_050_get_published_detail(self, api_client, auth_header, setup_articles):
        """ADM-050 已发布文章详情（含分类/标签嵌套 id）。"""
        published, _ = setup_articles
        response = api_client.get(f'/api/v1/admin/articles/{published.id}/', **auth_header)

        assert response.status_code == 200
        data = response.json()['data']
        assert data['title'] == '已发布文章'
        assert data['category']['id'] == published.category_id
        assert isinstance(data['tags'], list)

    def test_adm_051_get_draft_detail(self, api_client, auth_header, setup_articles):
        """ADM-051 草稿文章详情（公开接口不含，管理端必须返回）。"""
        _, draft = setup_articles
        response = api_client.get(f'/api/v1/admin/articles/{draft.id}/', **auth_header)

        assert response.status_code == 200
        assert response.json()['data']['slug'] == 'draft-post'

    def test_adm_052_unauthorized(self, api_client, setup_articles):
        """ADM-052 未登录 401。"""
        published, _ = setup_articles
        response = api_client.get(f'/api/v1/admin/articles/{published.id}/')

        assert response.status_code == 401

    def test_adm_053_not_found(self, api_client, auth_header):
        """ADM-053 不存在 id 404。"""
        response = api_client.get('/api/v1/admin/articles/9999/', **auth_header)

        assert response.status_code == 404
