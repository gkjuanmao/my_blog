"""文章归属转移：单篇 PUT（仅超管）与批量端点、审计字段、缓存失效。

编号 TRF-（transfer）。
"""
import pytest
from django.contrib.auth import get_user_model
from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart
from django.utils import timezone

from articles.models import Article

pytestmark = pytest.mark.django_db

BULK_AUTHOR_URL = '/api/v1/admin/articles/bulk-author/'
ADMIN_LIST_URL = '/api/v1/admin/articles/'
PUBLIC_LIST_URL = '/api/v1/articles/'


@pytest.fixture
def authors(db):
    """两位作者 + 一位停用用户 + 一位超管。"""
    User = get_user_model()
    owner = User.objects.create_superuser(username='root-trf', password='x', email='r@e.com')
    editor = User.objects.create_user(username='editor-trf', password='x', is_staff=True)
    other = User.objects.create_user(username='target-trf', password='x', is_staff=True)
    disabled = User.objects.create_user(username='gone-trf', password='x', is_active=False)
    return {'root': owner, 'editor': editor, 'target': other, 'disabled': disabled}


@pytest.fixture
def headers(authors):
    from ninja_jwt.tokens import RefreshToken

    def _h(user):
        return {'HTTP_AUTHORIZATION': f'Bearer {RefreshToken.for_user(user).access_token}'}

    return {key: _h(user) for key, user in authors.items()}


@pytest.fixture
def article(authors):
    return Article.objects.create(
        title='代传的游记',
        slug='dai-chuan',
        summary='',
        content='正文',
        publish_time=timezone.now(),
        author=authors['editor'],
        is_published=True,
    )


def put_article(api_client, header, article_id, data: dict):
    """multipart PUT（与前端 FormData 编码一致；Django 6 的 put() 不做 multipart 编码）。"""
    return api_client.put(
        f'/api/v1/admin/articles/{article_id}/',
        encode_multipart(BOUNDARY, data),
        content_type=MULTIPART_CONTENT,
        **header,
    )


class TestSingleTransfer:
    def test_trf_001_superuser_can_transfer(self, api_client, headers, article, authors):
        """TRF-001 超管改归属成功，并写入审计字段。"""
        response = put_article(
            api_client, headers['root'], article.pk, {'author_id': str(authors['target'].pk)}
        )

        assert response.status_code == 200, response.json()
        article.refresh_from_db()
        assert article.author_id == authors['target'].pk
        assert article.author_changed_at is not None
        assert article.author_changed_by_id == authors['root'].pk
        assert response.json()['data']['author_id'] == authors['target'].pk

    def test_trf_002_staff_cannot_transfer(self, api_client, headers, article, authors):
        """TRF-002 staff 改归属 403（能改别人的稿 ≠ 能把别人的稿划走）。"""
        response = put_article(
            api_client, headers['editor'], article.pk, {'author_id': str(authors['target'].pk)}
        )

        assert response.status_code == 403
        article.refresh_from_db()
        assert article.author_id == authors['editor'].pk

    def test_trf_003_staff_can_resubmit_same_author(self, api_client, headers, article, authors):
        """TRF-003 staff 提交自己当前的 author_id 不算转移，不应 403。

        否则「编辑表单把整个模型回传」的写法会被误伤。
        """
        response = put_article(
            api_client, headers['editor'], article.pk, {'author_id': str(authors['editor'].pk)}
        )

        assert response.status_code == 200
        article.refresh_from_db()
        assert article.author_changed_by_id is None  # 没动过就不写审计

    def test_trf_004_target_must_be_active(self, api_client, headers, article, authors):
        """TRF-004 转给停用用户 → 400（否则文章会挂到一个无法登录的账号上）。"""
        response = put_article(
            api_client, headers['root'], article.pk, {'author_id': str(authors['disabled'].pk)}
        )

        assert response.status_code == 400
        assert '停用' in response.json()['message']

    def test_trf_005_target_must_exist(self, api_client, headers, article):
        """TRF-005 目标用户不存在 → 400。"""
        response = put_article(api_client, headers['root'], article.pk, {'author_id': '999999'})

        assert response.status_code == 400

    def test_trf_006_public_cache_invalidated(self, api_client, headers, article, authors):
        """TRF-006 转移后公开列表立刻反映新作者（否则首页最多旧 60s）。"""
        api_client.get(PUBLIC_LIST_URL)  # 填充缓存
        before = api_client.get(PUBLIC_LIST_URL).json()['data']['items'][0]
        assert before['author_name'] == 'editor-trf'

        put_article(
            api_client, headers['root'], article.pk, {'author_id': str(authors['target'].pk)}
        )
        after = api_client.get(PUBLIC_LIST_URL).json()['data']['items'][0]

        assert after['author_name'] == 'target-trf'


class TestBulkTransfer:
    def test_trf_007_bulk_transfer(self, api_client, headers, article, authors):
        """TRF-007 批量转移：moved 计数、审计、not_found 回显。"""
        second = Article.objects.create(
            title='第二篇',
            slug='dai-chuan-2',
            publish_time=timezone.now(),
            author=authors['editor'],
        )
        response = api_client.post(
            BULK_AUTHOR_URL,
            {'ids': [article.pk, second.pk, 999999], 'author_id': authors['target'].pk},
            content_type='application/json',
            **headers['root'],
        )

        assert response.status_code == 200, response.json()
        data = response.json()['data']
        assert data['moved'] == 2
        assert data['not_found'] == [999999]
        assert Article.objects.filter(author=authors['target']).count() == 2
        article.refresh_from_db()
        assert article.author_changed_by_id == authors['root'].pk
        # QuerySet.update() 不触发信号，端点里显式失效过缓存；这里只断言数据已变
        assert article.updated_at is not None

    def test_trf_008_bulk_requires_superuser(self, api_client, headers, article, authors):
        """TRF-008 批量转移是超管专属端点（staff 403）。"""
        response = api_client.post(
            BULK_AUTHOR_URL,
            {'ids': [article.pk], 'author_id': authors['target'].pk},
            content_type='application/json',
            **headers['editor'],
        )

        assert response.status_code == 403

    def test_trf_009_bulk_rejects_empty_ids(self, api_client, headers, authors):
        """TRF-009 ids 为空 → 400。"""
        response = api_client.post(
            BULK_AUTHOR_URL,
            {'ids': [], 'author_id': authors['target'].pk},
            content_type='application/json',
            **headers['root'],
        )

        assert response.status_code == 400

    def test_trf_010_bulk_rejects_too_many_ids(self, api_client, headers, authors):
        """TRF-010 单次超过 200 篇 → 400（与批量删除同一上限）。"""
        response = api_client.post(
            BULK_AUTHOR_URL,
            {'ids': list(range(1, 202)), 'author_id': authors['target'].pk},
            content_type='application/json',
            **headers['root'],
        )

        assert response.status_code == 400


class TestAdminListAuthorFilter:
    def test_trf_011_admin_list_filters_by_author(self, api_client, headers, article, authors):
        """TRF-011 管理列表支持 ?author=（转移前先筛出来，才能批量划走）。"""
        Article.objects.create(
            title='别人的', slug='others', publish_time=timezone.now(), author=authors['target']
        )

        mine = api_client.get(f'{ADMIN_LIST_URL}?author={authors["editor"].pk}', **headers['root'])
        other = api_client.get(f'{ADMIN_LIST_URL}?author={authors["target"].pk}', **headers['root'])

        assert mine.json()['data']['total'] == 1
        assert mine.json()['data']['items'][0]['slug'] == 'dai-chuan'
        assert other.json()['data']['total'] == 1
        assert other.json()['data']['items'][0]['slug'] == 'others'
