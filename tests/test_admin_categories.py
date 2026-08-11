"""分类管理接口测试：/api/v1/admin/categories/ 增删改查。"""
import pytest
from django.utils import timezone

from articles.defaults import ensure_defaults
from articles.models import Article, Category


@pytest.mark.django_db
class TestAdminCategoryCreateAPI:
    def test_cat_050_normal_create(self, api_client, auth_header):
        """CAT-050 创建分类，slug 由名称自动生成。"""
        response = api_client.post(
            '/api/v1/admin/categories/',
            data={'name': '技术', 'description': '技术相关'},
            content_type='application/json',
            **auth_header,
        )

        assert response.status_code == 201
        data = response.json()['data']
        assert data['name'] == '技术'
        assert data['description'] == '技术相关'
        assert data['slug'] == 'ji-shu'

    def test_cat_051_manual_slug_wins(self, api_client, auth_header):
        """CAT-051 手动传入 slug 优先。"""
        response = api_client.post(
            '/api/v1/admin/categories/',
            data={'name': '技术', 'slug': 'tech'},
            content_type='application/json',
            **auth_header,
        )

        assert response.status_code == 201
        assert response.json()['data']['slug'] == 'tech'

    def test_cat_052_slug_conflict_auto_suffix(self, api_client, auth_header):
        """CAT-052 slug 冲突自动追加 -2 后缀。"""
        Category.objects.create(name='技术', slug='tech')

        response = api_client.post(
            '/api/v1/admin/categories/',
            data={'name': '技术', 'slug': 'tech'},
            content_type='application/json',
            **auth_header,
        )

        assert response.status_code == 201
        assert response.json()['data']['slug'] == 'tech-2'

    def test_cat_053_unauthorized(self, api_client):
        """CAT-053 未登录创建分类。"""
        response = api_client.post(
            '/api/v1/admin/categories/',
            data={'name': '技术'},
            content_type='application/json',
        )

        assert response.status_code == 401

    def test_cat_054_missing_name(self, api_client, auth_header):
        """CAT-054 缺少名称。"""
        response = api_client.post(
            '/api/v1/admin/categories/',
            data={'slug': 'tech'},
            content_type='application/json',
            **auth_header,
        )

        assert response.status_code == 422

    def test_cat_055_blank_name(self, api_client, auth_header):
        """CAT-055 名称为空白字符。"""
        response = api_client.post(
            '/api/v1/admin/categories/',
            data={'name': '   '},
            content_type='application/json',
            **auth_header,
        )

        assert response.status_code == 422


@pytest.mark.django_db
class TestAdminCategoryReadUpdateDeleteAPI:
    @pytest.fixture
    def category(self):
        return Category.objects.create(name='技术', slug='tech', description='旧描述')

    def test_cat_056_get_detail(self, api_client, auth_header, category):
        """CAT-056 获取分类详情。"""
        response = api_client.get(f'/api/v1/admin/categories/{category.pk}/', **auth_header)

        assert response.status_code == 200
        data = response.json()['data']
        assert data['id'] == category.pk
        assert data['name'] == '技术'
        assert data['slug'] == 'tech'

    def test_cat_057_get_not_found(self, api_client, auth_header):
        """CAT-057 分类不存在。"""
        response = api_client.get('/api/v1/admin/categories/999/', **auth_header)

        assert response.status_code == 404
        assert '不存在' in response.json()['message']

    def test_cat_058_update(self, api_client, auth_header, category):
        """CAT-058 更新名称与描述，省略 slug 保留原值。"""
        response = api_client.put(
            f'/api/v1/admin/categories/{category.pk}/',
            data={'name': '后端', 'description': '新描述'},
            content_type='application/json',
            **auth_header,
        )

        assert response.status_code == 200
        data = response.json()['data']
        assert data['name'] == '后端'
        assert data['description'] == '新描述'
        assert data['slug'] == 'tech'

    def test_cat_059_update_slug_conflict(self, api_client, auth_header, category):
        """CAT-059 更新 slug 冲突自动追加后缀。"""
        Category.objects.create(name='生活', slug='life')

        response = api_client.put(
            f'/api/v1/admin/categories/{category.pk}/',
            data={'name': '技术', 'slug': 'life'},
            content_type='application/json',
            **auth_header,
        )

        assert response.status_code == 200
        assert response.json()['data']['slug'] == 'life-2'

    def test_cat_060_update_not_found(self, api_client, auth_header):
        """CAT-060 更新不存在的分类。"""
        response = api_client.put(
            '/api/v1/admin/categories/999/',
            data={'name': '后端'},
            content_type='application/json',
            **auth_header,
        )

        assert response.status_code == 404

    def test_cat_061_delete(self, api_client, auth_header, category):
        """CAT-061 删除分类。"""
        response = api_client.delete(f'/api/v1/admin/categories/{category.pk}/', **auth_header)

        assert response.status_code == 200
        assert not Category.objects.filter(pk=category.pk).exists()

    def test_cat_062_delete_not_found(self, api_client, auth_header):
        """CAT-062 删除不存在的分类。"""
        response = api_client.delete('/api/v1/admin/categories/999/', **auth_header)

        assert response.status_code == 404

    def test_cat_063_delete_category_articles_kept(self, api_client, auth_header, category, user):
        """CAT-063 删除被文章使用的分类：文章保留，category 置空。"""
        article = Article.objects.create(
            title='文章', slug='post-1', content='内容',
            publish_time=timezone.now(), author=user, category=category,
        )

        response = api_client.delete(f'/api/v1/admin/categories/{category.pk}/', **auth_header)

        assert response.status_code == 200
        article.refresh_from_db()
        assert article.category is None

    def test_cat_064_delete_default_forbidden(self, api_client, auth_header):
        """CAT-064 默认分类不可删除。"""
        category, _ = ensure_defaults()

        response = api_client.delete(f'/api/v1/admin/categories/{category.pk}/', **auth_header)

        assert response.status_code == 400
        assert '默认分类不可删除' in response.json()['message']
        assert Category.objects.filter(slug='default-category').exists()
