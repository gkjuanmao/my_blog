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
            publish_time='2026-08-09T14:00:00Z',
            author=user,
        )

        response = api_client.post(
            '/api/v1/admin/articles/',
            {
                'title': '新文章',
                'slug': 'test',
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

    def test_adm_008b_html_attachment_rejected(
        self, api_client, auth_header, test_image, create_payload
    ):
        """ADM-008b HTML 附件被拒（决策 D19：附件白名单收紧为 PDF/Word）。

        HTML 与站点同源（/media/ 由 nginx 直出），上传即存储型 XSS 入口；
        导入侧另有"遗留扩展名"通道专门处理历史数据。
        """
        html_file = SimpleUploadedFile(
            'page.html', b'<html><body>test</body></html>', content_type='text/html'
        )
        response = api_client.post(
            '/api/v1/admin/articles/',
            {**create_payload, 'cover': test_image, 'attachment': html_file},
            **auth_header,
        )

        assert response.status_code == 400
        assert 'PDF/Word' in response.json()['message']
        assert not Article.objects.filter(slug='test-article').exists()

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
        """ADM-010 category_id/tag_ids 传空字符串视为未填，自动挂默认分类/标签。"""
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
        assert article.category is not None
        assert article.category.slug == 'default-category'
        assert list(article.tags.values_list('slug', flat=True)) == ['default-tag']

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


@pytest.mark.django_db
class TestCreateArticleDefaultsAPI:
    @pytest.fixture
    def create_payload(self):
        return {
            'title': '默认挂载测试',
            'slug': 'default-mount',
            'publish_time': '2026-08-09T14:00:00Z',
            'is_published': True,
        }

    def test_adm_013_default_category_and_tag_created(
        self, api_client, auth_header, test_image, test_pdf, create_payload
    ):
        """ADM-013 无分类/标签时创建文章，自动创建并使用默认分类/标签。"""
        response = api_client.post(
            '/api/v1/admin/articles/',
            {**create_payload, 'cover': test_image, 'attachment': test_pdf},
            **auth_header,
        )

        assert response.status_code == 201
        assert Category.objects.filter(slug='default-category').exists()
        assert Tag.objects.filter(slug='default-tag').exists()
        article = Article.objects.get(slug='default-mount')
        assert article.category.slug == 'default-category'
        assert list(article.tags.values_list('slug', flat=True)) == ['default-tag']

    def test_adm_014_defaults_reused(
        self, api_client, auth_header, test_image, test_pdf, create_payload
    ):
        """ADM-014 重复创建不产生重复默认数据。"""
        for index in range(2):
            payload = {**create_payload, 'slug': f'default-mount-{index}'}
            # 同一个 UploadedFile 被复用：multipart 编码会把它读到 EOF，
            # 不 seek 回去第二次就会发出空封面（现在会被"封面无法解析"挡下）
            test_image.seek(0)
            response = api_client.post(
                '/api/v1/admin/articles/',
                {**payload, 'cover': test_image, 'attachment': test_pdf},
                **auth_header,
            )
            assert response.status_code == 201

        assert Category.objects.filter(slug='default-category').count() == 1
        assert Tag.objects.filter(slug='default-tag').count() == 1

    def test_adm_015_explicit_category_tag_wins(
        self, api_client, auth_header, test_image, test_pdf, create_payload
    ):
        """ADM-015 显式传入分类/标签时不被默认覆盖。"""
        category = Category.objects.create(name='技术', slug='tech')
        tag = Tag.objects.create(name='Python', slug='python')
        payload = {**create_payload, 'category_id': category.id, 'tag_ids': [tag.id]}
        response = api_client.post(
            '/api/v1/admin/articles/',
            {**payload, 'cover': test_image, 'attachment': test_pdf},
            **auth_header,
        )

        assert response.status_code == 201
        article = Article.objects.get(slug='default-mount')
        assert article.category_id == category.id
        assert list(article.tags.values_list('id', flat=True)) == [tag.id]
        assert not Category.objects.filter(slug='default-category').exists()
        assert not Tag.objects.filter(slug='default-tag').exists()

    def test_adm_016_zero_sentinel_uses_default(
        self, api_client, auth_header, test_image, test_pdf, create_payload
    ):
        """ADM-016 category_id/tag_ids 传 '0' 占位值，视为未填并使用默认。"""
        payload = dict(create_payload)
        payload['slug'] = 'zero-sentinel'
        response = api_client.post(
            '/api/v1/admin/articles/',
            {
                **payload,
                'category_id': '0',
                'tag_ids': '0',
                'cover': test_image,
                'attachment': test_pdf,
            },
            **auth_header,
        )

        assert response.status_code == 201
        article = Article.objects.get(slug='zero-sentinel')
        assert article.category.slug == 'default-category'
        assert list(article.tags.values_list('slug', flat=True)) == ['default-tag']

    def test_adm_017_category_not_found(
        self, api_client, auth_header, test_image, test_pdf, create_payload
    ):
        """ADM-017 传不存在的 category_id 返回 400。"""
        response = api_client.post(
            '/api/v1/admin/articles/',
            {**create_payload, 'category_id': '999', 'cover': test_image, 'attachment': test_pdf},
            **auth_header,
        )

        assert response.status_code == 400
        assert '分类不存在' in response.json()['message']
        assert not Article.objects.exists()

    def test_adm_018_tag_not_found(
        self, api_client, auth_header, test_image, test_pdf, create_payload
    ):
        """ADM-018 传不存在的 tag_ids 返回 400。"""
        response = api_client.post(
            '/api/v1/admin/articles/',
            {**create_payload, 'tag_ids': '[999]', 'cover': test_image, 'attachment': test_pdf},
            **auth_header,
        )

        assert response.status_code == 400
        assert '标签不存在' in response.json()['message']
        assert not Article.objects.exists()

    def test_adm_019_failure_leaves_no_files(
        self, api_client, auth_header, test_image, test_pdf, create_payload, settings
    ):
        """ADM-019 校验失败不产生残留上传文件。"""
        media_root = settings.MEDIA_ROOT
        covers_dir = media_root / 'covers'
        files_dir = media_root / 'files'

        def snapshot() -> tuple[list[str], list[str]]:
            covers = sorted(p.name for p in covers_dir.iterdir()) if covers_dir.exists() else []
            files = sorted(p.name for p in files_dir.iterdir()) if files_dir.exists() else []
            return covers, files

        before = snapshot()
        response = api_client.post(
            '/api/v1/admin/articles/',
            {**create_payload, 'category_id': '999', 'cover': test_image, 'attachment': test_pdf},
            **auth_header,
        )

        assert response.status_code == 400
        assert snapshot() == before
