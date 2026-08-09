"""文章创建测试：slug 自动生成与唯一化。"""
import pytest
from django.utils import timezone
from django.utils.http import urlencode

from articles.models import Article


@pytest.mark.django_db
class TestSlugGenerationAPI:
    def test_adm_050_english_title_auto_slug(
        self, api_client, auth_header, test_image, test_pdf
    ):
        """ADM-050 英文标题自动生成 slug。"""
        response = api_client.post(
            '/api/v1/admin/articles/',
            {
                'title': 'Hello World',
                'content': '内容',
                'publish_time': '2026-08-09T14:00:00Z',
                'cover': test_image,
                'attachment': test_pdf,
            },
            **auth_header,
        )

        assert response.status_code == 201
        assert response.json()['data']['slug'] == 'hello-world'

    def test_adm_051_chinese_title_auto_slug(
        self, api_client, auth_header, test_image, test_pdf
    ):
        """ADM-051 中文标题自动生成拼音 slug。"""
        response = api_client.post(
            '/api/v1/admin/articles/',
            {
                'title': '第一篇测试文章',
                'content': '内容',
                'publish_time': '2026-08-09T14:00:00Z',
                'cover': test_image,
                'attachment': test_pdf,
            },
            **auth_header,
        )

        assert response.status_code == 201
        assert response.json()['data']['slug'] == 'di-yi-pian-ce-shi-wen-zhang'

    def test_adm_052_manual_slug_wins(
        self, api_client, auth_header, test_image, test_pdf
    ):
        """ADM-052 手动传入 slug 优先于自动生成。"""
        response = api_client.post(
            '/api/v1/admin/articles/',
            {
                'title': 'Hello World',
                'slug': 'my-custom-slug',
                'content': '内容',
                'publish_time': '2026-08-09T14:00:00Z',
                'cover': test_image,
                'attachment': test_pdf,
            },
            **auth_header,
        )

        assert response.status_code == 201
        assert response.json()['data']['slug'] == 'my-custom-slug'

    def test_adm_053_auto_slug_conflict(
        self, api_client, auth_header, test_image, test_pdf, user
    ):
        """ADM-053 自动生成的 slug 冲突时自动加后缀。"""
        Article.objects.create(
            title='已有', slug='hello-world', content='x',
            publish_time=timezone.now(), author=user,
        )
        response = api_client.post(
            '/api/v1/admin/articles/',
            {
                'title': 'Hello World',
                'content': '内容',
                'publish_time': '2026-08-09T14:00:00Z',
                'cover': test_image,
                'attachment': test_pdf,
            },
            **auth_header,
        )

        assert response.status_code == 201
        assert response.json()['data']['slug'] == 'hello-world-2'

    def test_adm_054_manual_slug_conflict(
        self, api_client, auth_header, test_image, test_pdf, user
    ):
        """ADM-054 手动传入的 slug 冲突时也自动加后缀。"""
        Article.objects.create(
            title='已有', slug='my-custom', content='x',
            publish_time=timezone.now(), author=user,
        )
        response = api_client.post(
            '/api/v1/admin/articles/',
            {
                'title': 'New',
                'slug': 'my-custom',
                'content': '内容',
                'publish_time': '2026-08-09T14:00:00Z',
                'cover': test_image,
                'attachment': test_pdf,
            },
            **auth_header,
        )

        assert response.status_code == 201
        assert response.json()['data']['slug'] == 'my-custom-2'


@pytest.mark.django_db
class TestUpdateSlugUniquenessAPI:
    def test_adm_055_update_slug_conflict(self, api_client, auth_header, user):
        """ADM-055 更新 slug 冲突时加后缀，且排除自身。"""
        a1 = Article.objects.create(
            title='A', slug='a', content='x', publish_time=timezone.now(), author=user,
        )
        Article.objects.create(
            title='B', slug='b', content='x', publish_time=timezone.now(), author=user,
        )

        # 更新为已存在的 slug -> 自动加后缀
        response = api_client.put(
            f'/api/v1/admin/articles/{a1.id}/',
            urlencode({'slug': 'b'}),
            content_type='application/x-www-form-urlencoded',
            **auth_header,
        )
        assert response.status_code == 200
        a1.refresh_from_db()
        assert a1.slug == 'b-2'

        # 更新为自身当前 slug -> 不应误判冲突
        response = api_client.put(
            f'/api/v1/admin/articles/{a1.id}/',
            urlencode({'slug': 'b-2'}),
            content_type='application/x-www-form-urlencoded',
            **auth_header,
        )
        assert response.status_code == 200
        a1.refresh_from_db()
        assert a1.slug == 'b-2'
