"""文章管理接口测试：POST /api/v1/admin/articles/（创建）。"""
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from articles.models import Article, Category, Tag


@pytest.mark.django_db
class TestCreateArticleAPI:
    @pytest.fixture
    def setup_data(self, user):
        category = Category.objects.create(name='技术', slug='tech')
        tag = Tag.objects.create(name='Python', slug='python')
        return category, tag

    @pytest.fixture
    def create_payload(self):
        return {
            'title': '测试文章',
            'slug': 'test-article',
            'content': '# 内容',
            'publish_time': '2026-08-09T14:00:00Z',
            'is_published': True,
        }

    def test_adm_001_normal_create(
        self, api_client, auth_header, test_image, test_pdf, setup_data, create_payload
    ):
        """ADM-001 正常创建文章。"""
        category, tag = setup_data
        payload = {**create_payload, 'category_id': category.id, 'tag_ids': [tag.id]}
        response = api_client.post(
            '/api/v1/admin/articles/',
            {**payload, 'cover': test_image, 'attachment': test_pdf},
            **auth_header,
        )

        assert response.status_code == 201
        data = response.json()['data']
        assert data['title'] == '测试文章'
        assert data['cover_image_name'] == 'test.jpg'
        assert data['file_name'] == 'test.pdf'

        article = Article.objects.get(slug='test-article')
        assert article.cover_image_name == 'test.jpg'

    def test_adm_002_unauthorized(self, api_client, test_image, test_pdf, create_payload):
        """ADM-002 未登录创建。"""
        response = api_client.post(
            '/api/v1/admin/articles/',
            {**create_payload, 'cover': test_image, 'attachment': test_pdf},
        )

        assert response.status_code == 401

    def test_adm_003_missing_title(
        self, api_client, auth_header, test_image, test_pdf, create_payload
    ):
        """ADM-003 缺少 title。"""
        payload = dict(create_payload)
        payload.pop('title')
        response = api_client.post(
            '/api/v1/admin/articles/',
            {**payload, 'cover': test_image, 'attachment': test_pdf},
            **auth_header,
        )

        assert response.status_code == 422

    def test_adm_004_missing_cover(self, api_client, auth_header, test_pdf, create_payload):
        """ADM-004 缺少 cover 文件。"""
        response = api_client.post(
            '/api/v1/admin/articles/',
            {**create_payload, 'attachment': test_pdf},
            **auth_header,
        )

        assert response.status_code == 422

    def test_adm_005_duplicate_slug(self, api_client, auth_header, user, test_image, test_pdf):
        """ADM-005 slug 重复时自动加后缀。"""
        Article.objects.create(
            title='已存在',
            slug='test',
            content='内容',
            publish_time='2026-08-09T14:00:00Z',
            author=user,
        )

        response = api_client.post(
            '/api/v1/admin/articles/',
            {
                'title': '新文章',
                'slug': 'test',
                'content': '内容',
                'publish_time': '2026-08-09T14:00:00Z',
                'cover': test_image,
                'attachment': test_pdf,
            },
            **auth_header,
        )

        assert response.status_code == 201
        assert response.json()['data']['slug'] == 'test-2'

    def test_adm_006_invalid_cover_type(self, api_client, auth_header, test_pdf, create_payload):
        """ADM-006 封面格式错误。"""
        bad_file = SimpleUploadedFile(
            'bad.exe', b'MZ' + b'x' * 100, content_type='application/octet-stream'
        )
        response = api_client.post(
            '/api/v1/admin/articles/',
            {**create_payload, 'cover': bad_file, 'attachment': test_pdf},
            **auth_header,
        )

        assert response.status_code == 400

    def test_adm_007_cover_too_large(self, api_client, auth_header, test_pdf, create_payload):
        """ADM-007 封面超过 20MB。"""
        big_file = SimpleUploadedFile(
            'big.jpg', b'x' * (21 * 1024 * 1024), content_type='image/jpeg'
        )
        response = api_client.post(
            '/api/v1/admin/articles/',
            {**create_payload, 'cover': big_file, 'attachment': test_pdf},
            **auth_header,
        )

        assert response.status_code == 400

    def test_adm_008_invalid_attachment_type(
        self, api_client, auth_header, test_image, create_payload
    ):
        """ADM-008 附件格式错误。"""
        bad_file = SimpleUploadedFile(
            'bad.exe', b'MZ' + b'x' * 100, content_type='application/octet-stream'
        )
        response = api_client.post(
            '/api/v1/admin/articles/',
            {**create_payload, 'cover': test_image, 'attachment': bad_file},
            **auth_header,
        )

        assert response.status_code == 400

    def test_adm_009_chinese_filename(self, api_client, auth_header, test_pdf, create_payload):
        """ADM-009 中文文件名：物理文件 UUID 化，保留原始文件名。"""
        img = Image.new('RGB', (20, 20), color='blue')
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG')
        buffer.seek(0)
        cn_file = SimpleUploadedFile('测试.jpg', buffer.read(), content_type='image/jpeg')

        response = api_client.post(
            '/api/v1/admin/articles/',
            {**create_payload, 'cover': cn_file, 'attachment': test_pdf},
            **auth_header,
        )

        assert response.status_code == 201
        data = response.json()['data']
        assert data['cover_image_name'] == '测试.jpg'
        article = Article.objects.get(slug='test-article')
        assert article.cover_image.name.startswith('covers/')

    def test_adm_010_empty_category_and_tags(
        self, api_client, auth_header, test_image, test_pdf, create_payload
    ):
        """ADM-010 category_id/tag_ids 传空字符串视为未填。"""
        payload = dict(create_payload)
        payload['slug'] = 'empty-cat-tags'
        response = api_client.post(
            '/api/v1/admin/articles/',
            {
                **payload,
                'category_id': '',
                'tag_ids': '',
                'cover': test_image,
                'attachment': test_pdf,
            },
            **auth_header,
        )

        assert response.status_code == 201
        article = Article.objects.get(slug='empty-cat-tags')
        assert article.category is None
        assert article.tags.count() == 0

    def test_adm_011_tag_ids_json_string(
        self, api_client, auth_header, test_image, test_pdf, setup_data, create_payload
    ):
        """ADM-011 tag_ids 传 JSON 数组字符串（Swagger UI 编码）。"""
        _, tag = setup_data
        payload = dict(create_payload)
        payload['slug'] = 'json-tags'
        response = api_client.post(
            '/api/v1/admin/articles/',
            {
                **payload,
                'tag_ids': f'[{tag.id}]',
                'cover': test_image,
                'attachment': test_pdf,
            },
            **auth_header,
        )

        assert response.status_code == 201
        article = Article.objects.get(slug='json-tags')
        assert list(article.tags.values_list('id', flat=True)) == [tag.id]

    def test_adm_012_tag_ids_repeated_fields(
        self, api_client, auth_header, test_image, test_pdf, setup_data, create_payload
    ):
        """ADM-012 tag_ids 用重复字段（curl 编码）。"""
        category, tag = setup_data
        payload = dict(create_payload)
        payload['slug'] = 'repeated-tags'
        response = api_client.post(
            '/api/v1/admin/articles/',
            {
                **payload,
                'category_id': str(category.id),
                'tag_ids': [str(tag.id)],
                'cover': test_image,
                'attachment': test_pdf,
            },
            **auth_header,
        )

        assert response.status_code == 201
        article = Article.objects.get(slug='repeated-tags')
        assert article.category_id == category.id
        assert list(article.tags.values_list('id', flat=True)) == [tag.id]
