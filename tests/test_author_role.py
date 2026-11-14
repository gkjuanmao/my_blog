"""作者本人的稿件权限：非 staff 只能动自己的稿，staff 仍管全站。

编号 ROLE-。「别人的稿一律 404」是刻意的：403 等于确认这个 id 存在，
而草稿的存在性本身就是信息。
"""
import pytest
from django.contrib.auth import get_user_model
from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart
from django.utils import timezone

from articles.models import Article

pytestmark = pytest.mark.django_db

ADMIN_LIST_URL = '/api/v1/admin/articles/'


@pytest.fixture
def two_authors(db):
    User = get_user_model()
    alice = User.objects.create_user(username='alice', password='x')
    bob = User.objects.create_user(username='bob', password='x')
    return {'alice': alice, 'bob': bob}


@pytest.fixture
def headers(two_authors):
    from ninja_jwt.tokens import RefreshToken

    return {
        key: {'HTTP_AUTHORIZATION': f'Bearer {RefreshToken.for_user(user).access_token}'}
        for key, user in two_authors.items()
    }


@pytest.fixture
def alice_article(two_authors):
    return Article.objects.create(
        title='Alice 的草稿',
        slug='alice-draft',
        publish_time=timezone.now(),
        author=two_authors['alice'],
        is_published=False,
    )


@pytest.fixture
def bob_article(two_authors):
    return Article.objects.create(
        title='Bob 的草稿',
        slug='bob-draft',
        publish_time=timezone.now(),
        author=two_authors['bob'],
        is_published=False,
    )


def put_article(api_client, header, article_id, data):
    return api_client.put(
        f'{ADMIN_LIST_URL}{article_id}/',
        encode_multipart(BOUNDARY, data),
        content_type=MULTIPART_CONTENT,
        **header,
    )


class TestAuthorScope:
    def test_role_001_list_only_own(self, api_client, headers, alice_article, bob_article):
        """ROLE-001 普通作者的管理列表只有自己的稿。"""
        data = api_client.get(ADMIN_LIST_URL, **headers['alice']).json()['data']

        assert data['total'] == 1
        assert data['items'][0]['slug'] == 'alice-draft'

    def test_role_002_other_draft_is_404(self, api_client, headers, bob_article):
        """ROLE-002 读别人的稿 → 404（不确认存在性）。"""
        response = api_client.get(f'{ADMIN_LIST_URL}{bob_article.pk}/', **headers['alice'])

        assert response.status_code == 404

    def test_role_003_cannot_update_other(self, api_client, headers, bob_article):
        """ROLE-003 改别人的稿 → 404，且数据不变。"""
        response = put_article(api_client, headers['alice'], bob_article.pk, {'title': '被改了'})

        assert response.status_code == 404
        bob_article.refresh_from_db()
        assert bob_article.title == 'Bob 的草稿'

    def test_role_004_cannot_delete_other(self, api_client, headers, bob_article):
        """ROLE-004 删别人的稿 → 404，且文章还在。"""
        assert (
            api_client.delete(f'{ADMIN_LIST_URL}{bob_article.pk}/', **headers['alice']).status_code
            == 404
        )
        assert (
            api_client.delete(
                f'{ADMIN_LIST_URL}slug/bob-draft/', **headers['alice']
            ).status_code
            == 404
        )
        assert Article.objects.filter(pk=bob_article.pk).exists()

    def test_role_005_can_update_own(self, api_client, headers, alice_article):
        """ROLE-005 改自己的稿 → 200。"""
        response = put_article(api_client, headers['alice'], alice_article.pk, {'title': '改好了'})

        assert response.status_code == 200, response.json()
        alice_article.refresh_from_db()
        assert alice_article.title == '改好了'

    def test_role_006_create_lands_on_self(
        self, api_client, headers, two_authors, jpeg_factory
    ):
        """ROLE-006 普通作者新建文章，作者恒为本人（不能指定别人）。"""
        from django.core.files.uploadedfile import SimpleUploadedFile

        payload = {
            'title': '新建的稿',
            'publish_time': timezone.now().isoformat(),
            'content': '正文',
            'is_published': 'false',
            'tag_ids': '[]',
            'author_id': str(two_authors['bob'].pk),  # 想塞给别人，应被忽略
        }
        payload['cover'] = SimpleUploadedFile('c.jpg', jpeg_factory(), content_type='image/jpeg')

        # post() 自己会按 content_type 做 multipart 编码，别再手工 encode 一次
        response = api_client.post(
            ADMIN_LIST_URL, payload, content_type=MULTIPART_CONTENT, **headers['alice']
        )

        assert response.status_code == 201, response.json()
        article = Article.objects.get(slug__startswith='xin-jian')
        assert article.author_id == two_authors['alice'].pk

    def test_role_007_bulk_delete_scoped(self, api_client, headers, alice_article, bob_article):
        """ROLE-007 批量删除只能删自己的：别人的 id 归入 not_found，不报错也不删。"""
        response = api_client.post(
            f'{ADMIN_LIST_URL}bulk-delete/',
            {'ids': [alice_article.pk, bob_article.pk]},
            content_type='application/json',
            **headers['alice'],
        )

        assert response.status_code == 200, response.json()
        data = response.json()['data']
        assert data['deleted'] == 1
        assert data['not_found'] == [bob_article.pk]
        assert not Article.objects.filter(pk=alice_article.pk).exists()
        assert Article.objects.filter(pk=bob_article.pk).exists()

    def test_role_008_staff_still_sees_all(
        self, api_client, staff_header, alice_article, bob_article
    ):
        """ROLE-008 回归：staff 仍看全站、仍能改别人的稿（编辑视角不变）。"""
        data = api_client.get(ADMIN_LIST_URL, **staff_header).json()['data']
        assert data['total'] == 2

        response = put_article(api_client, staff_header, bob_article.pk, {'title': '编辑改的'})
        assert response.status_code == 200
        bob_article.refresh_from_db()
        assert bob_article.title == '编辑改的'
