"""媒体 URL 契约测试：cover_image_url / file_url 必须为相对路径（以 /media/ 开头）。"""

import pytest


def assert_relative_media_url(data: dict) -> None:
    """断言封面与附件 URL 为相对路径：以 /media/ 开头且不以 http 开头。"""
    for field in ('cover_image_url', 'file_url'):
        url = data[field]
        assert url is not None
        assert url.startswith('/media/'), f'{field}={url!r} 应以 /media/ 开头'
        assert not url.startswith('http'), f'{field}={url!r} 不应为绝对 URL'


@pytest.mark.django_db
class TestMediaUrlRelativeContract:
    @pytest.fixture
    def create_payload(self):
        return {
            'title': '媒体 URL 测试',
            'slug': 'media-url-test',
            'publish_time': '2026-08-17T14:00:00Z',
            'is_published': True,
        }

    @pytest.fixture
    def created_article(self, api_client, auth_header, test_image, test_pdf, create_payload):
        response = api_client.post(
            '/api/v1/admin/articles/',
            {**create_payload, 'cover': test_image, 'attachment': test_pdf},
            **auth_header,
        )
        assert response.status_code == 201
        return response.json()['data']

    def test_pub_001_list_returns_relative_media_url(
        self, api_client, created_article
    ):
        """列表接口返回相对 /media/ 路径。"""
        response = api_client.get('/api/v1/articles/')
        assert response.status_code == 200
        items = response.json()['data']['items']
        assert len(items) == 1
        assert_relative_media_url(items[0])

    def test_pub_002_detail_returns_relative_media_url(
        self, api_client, created_article
    ):
        """详情接口返回相对 /media/ 路径。"""
        response = api_client.get('/api/v1/articles/media-url-test/')
        assert response.status_code == 200
        assert_relative_media_url(response.json()['data'])

    def test_adm_001_admin_list_returns_relative_media_url(
        self, api_client, auth_header, created_article
    ):
        """管理列表接口返回相对 /media/ 路径。"""
        response = api_client.get('/api/v1/admin/articles/', **auth_header)
        assert response.status_code == 200
        items = response.json()['data']['items']
        assert len(items) == 1
        assert_relative_media_url(items[0])
