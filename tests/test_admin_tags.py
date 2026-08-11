"""标签管理接口测试：/api/v1/admin/tags/ 增删改查。"""
import pytest
from django.utils import timezone

from articles.defaults import ensure_defaults
from articles.models import Article, Tag


@pytest.mark.django_db
class TestAdminTagCreateAPI:
    def test_tag_050_normal_create(self, api_client, auth_header):
        """TAG-050 创建标签，slug 由名称自动生成。"""
        response = api_client.post(
            '/api/v1/admin/tags/',
            data={'name': 'Python'},
            content_type='application/json',
            **auth_header,
        )

        assert response.status_code == 201
        data = response.json()['data']
        assert data['name'] == 'Python'
        assert data['slug'] == 'python'

    def test_tag_051_chinese_name_auto_slug(self, api_client, auth_header):
        """TAG-051 中文名称自动转拼音 slug。"""
        response = api_client.post(
            '/api/v1/admin/tags/',
            data={'name': '后端'},
            content_type='application/json',
            **auth_header,
        )

        assert response.status_code == 201
        assert response.json()['data']['slug'] == 'hou-duan'

    def test_tag_052_slug_conflict_auto_suffix(self, api_client, auth_header):
        """TAG-052 slug 冲突自动追加 -2 后缀。"""
        Tag.objects.create(name='Python', slug='python')

        response = api_client.post(
            '/api/v1/admin/tags/',
            data={'name': 'Python', 'slug': 'python'},
            content_type='application/json',
            **auth_header,
        )

        assert response.status_code == 201
        assert response.json()['data']['slug'] == 'python-2'

    def test_tag_053_unauthorized(self, api_client):
        """TAG-053 未登录创建标签。"""
        response = api_client.post(
            '/api/v1/admin/tags/',
            data={'name': 'Python'},
            content_type='application/json',
        )

        assert response.status_code == 401

    def test_tag_054_blank_name(self, api_client, auth_header):
        """TAG-054 名称为空白字符。"""
        response = api_client.post(
            '/api/v1/admin/tags/',
            data={'name': '  '},
            content_type='application/json',
            **auth_header,
        )

        assert response.status_code == 422


@pytest.mark.django_db
class TestAdminTagReadUpdateDeleteAPI:
    @pytest.fixture
    def tag(self):
        return Tag.objects.create(name='Python', slug='python')

    def test_tag_055_get_detail(self, api_client, auth_header, tag):
        """TAG-055 获取标签详情。"""
        response = api_client.get(f'/api/v1/admin/tags/{tag.pk}/', **auth_header)

        assert response.status_code == 200
        assert response.json()['data']['name'] == 'Python'

    def test_tag_056_get_not_found(self, api_client, auth_header):
        """TAG-056 标签不存在。"""
        response = api_client.get('/api/v1/admin/tags/999/', **auth_header)

        assert response.status_code == 404

    def test_tag_057_update(self, api_client, auth_header, tag):
        """TAG-057 更新名称，省略 slug 保留原值。"""
        response = api_client.put(
            f'/api/v1/admin/tags/{tag.pk}/',
            data={'name': 'Django'},
            content_type='application/json',
            **auth_header,
        )

        assert response.status_code == 200
        data = response.json()['data']
        assert data['name'] == 'Django'
        assert data['slug'] == 'python'

    def test_tag_058_update_slug(self, api_client, auth_header, tag):
        """TAG-058 更新 slug。"""
        response = api_client.put(
            f'/api/v1/admin/tags/{tag.pk}/',
            data={'name': 'Python', 'slug': 'py'},
            content_type='application/json',
            **auth_header,
        )

        assert response.status_code == 200
        assert response.json()['data']['slug'] == 'py'

    def test_tag_059_update_not_found(self, api_client, auth_header):
        """TAG-059 更新不存在的标签。"""
        response = api_client.put(
            '/api/v1/admin/tags/999/',
            data={'name': 'Django'},
            content_type='application/json',
            **auth_header,
        )

        assert response.status_code == 404

    def test_tag_060_delete(self, api_client, auth_header, tag):
        """TAG-060 删除标签。"""
        response = api_client.delete(f'/api/v1/admin/tags/{tag.pk}/', **auth_header)

        assert response.status_code == 200
        assert not Tag.objects.filter(pk=tag.pk).exists()

    def test_tag_061_delete_not_found(self, api_client, auth_header):
        """TAG-061 删除不存在的标签。"""
        response = api_client.delete('/api/v1/admin/tags/999/', **auth_header)

        assert response.status_code == 404

    def test_tag_062_delete_tag_removes_from_article(self, api_client, auth_header, tag, user):
        """TAG-062 删除被文章使用的标签：仅解除 M2M 关联，文章保留。"""
        article = Article.objects.create(
            title='文章', slug='post-1', content='内容',
            publish_time=timezone.now(), author=user,
        )
        article.tags.add(tag)

        response = api_client.delete(f'/api/v1/admin/tags/{tag.pk}/', **auth_header)

        assert response.status_code == 200
        assert not Tag.objects.filter(pk=tag.pk).exists()
        article.refresh_from_db()
        assert article.tags.count() == 0

    def test_tag_063_delete_default_forbidden(self, api_client, auth_header):
        """TAG-063 默认标签不可删除。"""
        _, tag = ensure_defaults()

        response = api_client.delete(f'/api/v1/admin/tags/{tag.pk}/', **auth_header)

        assert response.status_code == 400
        assert '默认标签不可删除' in response.json()['message']
        assert Tag.objects.filter(slug='default-tag').exists()
