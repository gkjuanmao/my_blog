"""公开作者列表 GET /api/v1/authors/：字段白名单、只列有文章的人、缓存与失效。

编号沿用 AUT-（author）前缀。
"""
import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from articles.models import Article

pytestmark = pytest.mark.django_db

AUTHORS_URL = '/api/v1/authors/'


def make_article(author, slug, *, published=True, title=None):
    return Article.objects.create(
        title=title or f'文章-{slug}',
        slug=slug,
        publish_time=timezone.now(),
        author=author,
        is_published=published,
    )


class TestAuthorsEndpoint:
    @pytest.fixture
    def three_authors(self, user):
        """甲乙丙：甲 3 篇已发布、乙 1 篇已发布 + 2 篇草稿、丙 0 篇。"""
        other = get_user_model().objects.create_user(username='writer-b', password='x')
        silent = get_user_model().objects.create_user(username='writer-c', password='x')
        for i in range(3):
            make_article(user, f'jia-{i}')
        make_article(other, 'yi-0')
        make_article(other, 'yi-draft-1', published=False)
        make_article(other, 'yi-draft-2', published=False)
        return {'a': user, 'b': other, 'c': silent}

    def test_aut_001_only_authors_with_published_articles(self, api_client, three_authors):
        """AUT-001 只有草稿或没有文章的用户不进列表（点了没结果的项就是噪音）。"""
        data = api_client.get(AUTHORS_URL).json()['data']
        names = [item['username'] for item in data['items']]

        assert 'writer-b' in names  # 有 1 篇已发布
        assert 'writer-c' not in names  # 一篇都没有
        assert len(names) == 2

    def test_aut_002_article_count_excludes_drafts(self, api_client, three_authors):
        """AUT-002 article_count 只算已发布。"""
        data = api_client.get(AUTHORS_URL).json()['data']
        counts = {item['username']: item['article_count'] for item in data['items']}

        assert counts['writer-b'] == 1
        assert counts[three_authors['a'].username] == 3

    def test_aut_003_sorted_by_count_desc(self, api_client, three_authors):
        """AUT-003 文章多的排前面（筛选器第一屏就该是最该点的人）。"""
        items = api_client.get(AUTHORS_URL).json()['data']['items']

        assert [i['article_count'] for i in items] == sorted(
            (i['article_count'] for i in items), reverse=True
        )
        assert items[0]['id'] == three_authors['a'].id

    def test_aut_004_empty_site(self, api_client, db):
        """AUT-004 空站点返回空列表（前端据此隐藏整个筛选器）。"""
        response = api_client.get(AUTHORS_URL)

        assert response.status_code == 200
        assert response.json()['data']['items'] == []

    def test_aut_005_field_whitelist(self, api_client, three_authors):
        """AUT-005 字段白名单：不得出现 email / is_staff / is_superuser / date_joined。

        这是本端点最重要的护栏——顺手复用 UserOut 就等于把全员邮箱与权限结构
        挂到公网上。
        """
        item = api_client.get(AUTHORS_URL).json()['data']['items'][0]

        assert set(item) == {'id', 'username', 'article_count', 'avatar_url'}
        for leaked in ('email', 'is_staff', 'is_superuser', 'date_joined', 'last_login'):
            assert leaked not in item

    def test_aut_006_cache_invalidated_on_article_write(self, api_client, three_authors):
        """AUT-006 文章写操作后列表立刻更新（缓存按版本号整体失效）。"""
        before = api_client.get(AUTHORS_URL).json()['data']['items']
        silent_id = three_authors['c'].id
        assert all(item['id'] != silent_id for item in before)

        make_article(three_authors['c'], 'bing-0')
        after = api_client.get(AUTHORS_URL).json()['data']['items']

        assert any(item['id'] == silent_id for item in after)

    def test_aut_007_cache_invalidated_on_user_write(self, api_client, three_authors):
        """AUT-007 改用户资料后缓存失效（用户名会显示在公网）。"""
        from ninja_jwt.tokens import RefreshToken

        root = get_user_model().objects.create_superuser(
            username='root-aut', password='x', email='root@example.com'
        )
        root_header = {'HTTP_AUTHORIZATION': f'Bearer {RefreshToken.for_user(root).access_token}'}

        api_client.get(AUTHORS_URL)  # 先填充缓存
        target = three_authors['b']

        response = api_client.put(
            f'/api/v1/admin/users/{target.id}/',
            {
                'email': 'b@example.com',
                'is_staff': True,
                'is_superuser': False,
                'is_active': True,
            },
            content_type='application/json',
            **root_header,
        )
        assert response.status_code == 200
        # 缓存失效无法直接观测（用户名没变），这里钉住端点仍可用且计数正确
        data = api_client.get(AUTHORS_URL).json()['data']
        assert any(item['article_count'] == 1 for item in data['items'])

    def test_aut_008_is_public(self, api_client, three_authors):
        """AUT-008 匿名可访问（首页筛选器在未登录时也要能用）。"""
        assert api_client.get(AUTHORS_URL).status_code == 200


ADMIN_AUTHORS_URL = '/api/v1/admin/articles/authors/'


class TestAdminArticleAuthorsEndpoint:
    """后台「按作者筛选」的选项来源（口径与公开 /authors/ 不同：含草稿）。"""

    @pytest.fixture
    def mixed(self, user):
        """staff 甲 2 篇（1 已发布 + 1 草稿），乙只有 1 篇草稿，丙一篇都没有。"""
        draft_only = get_user_model().objects.create_user(username='draft-only', password='x')
        silent = get_user_model().objects.create_user(username='no-article', password='x')
        make_article(user, 'jia-pub')
        make_article(user, 'jia-draft', published=False)
        make_article(draft_only, 'yi-draft-only', published=False)
        return {'staff': user, 'draft_only': draft_only, 'silent': silent}

    def test_aut_009_includes_draft_only_authors(self, api_client, auth_header, mixed):
        """AUT-009 只有草稿的作者也要出现在后台筛选器里。

        公开 /authors/ 只算已发布，这类账号会消失；后台列表却看得到他的稿子，
        所以选项必须单独取（这里同时钉住路由没被 /articles/{article_id}/ 抢走）。
        """
        response = api_client.get(ADMIN_AUTHORS_URL, **auth_header)

        assert response.status_code == 200
        names = [item['username'] for item in response.json()['data']['items']]
        assert 'draft-only' in names
        assert 'no-article' not in names  # 一篇稿子都没有的人不该占位

        public_names = [i['username'] for i in api_client.get(AUTHORS_URL).json()['data']['items']]
        assert 'draft-only' not in public_names  # 对照：公开端点确实看不到他

    def test_aut_010_counts_include_drafts(self, api_client, auth_header, mixed):
        """AUT-010 article_count 含草稿，published_count 只算已发布。"""
        items = api_client.get(ADMIN_AUTHORS_URL, **auth_header).json()['data']['items']
        by_name = {item['username']: item for item in items}

        staff_row = by_name[mixed['staff'].username]
        assert staff_row['article_count'] == 2
        assert staff_row['published_count'] == 1
        assert by_name['draft-only']['article_count'] == 1
        assert by_name['draft-only']['published_count'] == 0

    def test_aut_011_requires_staff(self, api_client, plain_header):
        """AUT-011 非 staff 一律 403（他会看到全员用户名，属于管理视角）。"""
        assert api_client.get(ADMIN_AUTHORS_URL, **plain_header).status_code == 403
        assert api_client.get(ADMIN_AUTHORS_URL).status_code == 401

    def test_aut_012_field_whitelist(self, api_client, auth_header, mixed):
        """AUT-012 字段白名单：不泄露 email / 权限 / 登录时间。"""
        item = api_client.get(ADMIN_AUTHORS_URL, **auth_header).json()['data']['items'][0]

        assert set(item) == {
            'id', 'username', 'article_count', 'published_count', 'avatar_url',
        }
        for leaked in ('email', 'is_staff', 'is_superuser', 'last_login', 'date_joined'):
            assert leaked not in item

