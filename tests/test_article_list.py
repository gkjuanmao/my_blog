"""文章公开接口测试：GET /api/v1/articles/（分页）。"""
import pytest
from django.utils import timezone

from articles.models import Article, Category, Tag


@pytest.mark.django_db
class TestArticleListAPI:
    @pytest.fixture
    def setup_articles(self, user):
        """创建 15 篇已发布文章与 1 篇草稿，部分文章挂标签。"""
        category = Category.objects.create(name='技术', slug='tech')
        travel = Tag.objects.create(name='旅行', slug='travel')
        food = Tag.objects.create(name='美食', slug='food')
        for i in range(15):
            article = Article.objects.create(
                title=f'文章{i}',
                slug=f'article-{i}',
                publish_time=timezone.now(),
                author=user,
                category=category,
                is_published=True,
            )
            if i < 5:
                article.tags.add(travel)
            elif i < 8:
                article.tags.add(food)
        Article.objects.create(
            title='草稿',
            slug='draft',
            publish_time=timezone.now(),
            author=user,
            is_published=False,
        )

    def test_art_001_default_pagination(self, api_client, setup_articles):
        """ART-001 默认分页：第 1 页 10 条。"""
        response = api_client.get('/api/v1/articles/')

        assert response.status_code == 200
        data = response.json()['data']
        assert len(data['items']) == 10
        assert data['total'] == 15
        assert data['page'] == 1

    def test_art_002_page_2(self, api_client, setup_articles):
        """ART-002 第 2 页返回 5 条。"""
        response = api_client.get('/api/v1/articles/?page=2')

        assert response.status_code == 200
        data = response.json()['data']
        assert len(data['items']) == 5

    def test_art_003_custom_page_size(self, api_client, setup_articles):
        """ART-003 自定义 page_size=5。"""
        response = api_client.get('/api/v1/articles/?page_size=5')

        assert response.status_code == 200
        assert len(response.json()['data']['items']) == 5

    def test_art_004_invalid_page(self, api_client):
        """ART-004 非法 page=0。"""
        response = api_client.get('/api/v1/articles/?page=0')

        assert response.status_code == 422

    def test_art_005_only_published(self, api_client, setup_articles):
        """ART-005 草稿不出现在列表中。"""
        response = api_client.get('/api/v1/articles/')

        data = response.json()['data']
        slugs = [item['slug'] for item in data['items']]
        assert 'draft' not in slugs

    def test_art_006_filter_by_category(self, api_client, setup_articles):
        """ART-006 按 category_slug 过滤。"""
        response = api_client.get('/api/v1/articles/?category_slug=tech')

        assert response.status_code == 200
        assert response.json()['data']['total'] == 15

    def test_art_007_empty_database(self, api_client):
        """ART-007 空数据库。"""
        response = api_client.get('/api/v1/articles/')

        assert response.status_code == 200
        data = response.json()['data']
        assert data['items'] == []
        assert data['total'] == 0

    def test_art_008_filter_by_tag(self, api_client, setup_articles):
        """ART-008 按 tag_slug 过滤。"""
        response = api_client.get('/api/v1/articles/?tag_slug=travel')

        assert response.status_code == 200
        data = response.json()['data']
        assert data['total'] == 5
        assert all(
            any(t['slug'] == 'travel' for t in item['tags'])
            for item in data['items']
        )

    def test_art_009_filter_by_tag_no_hit(self, api_client, setup_articles):
        """ART-009 tag_slug 无命中。"""
        response = api_client.get('/api/v1/articles/?tag_slug=no-such')

        assert response.status_code == 200
        data = response.json()['data']
        assert data['items'] == []
        assert data['total'] == 0

    def test_art_010_filter_by_category_and_tag(self, api_client, setup_articles):
        """ART-010 category_slug + tag_slug 组合过滤。"""
        response = api_client.get('/api/v1/articles/?category_slug=tech&tag_slug=travel')

        assert response.status_code == 200
        assert response.json()['data']['total'] == 5

    # ------------------------------------------------------------------ 作者维度

    @pytest.fixture
    def two_authors(self, user):
        """两个作者：甲 3 篇已发布、乙 2 篇已发布 + 1 篇草稿，另有一篇分类不同的。"""
        from django.contrib.auth import get_user_model

        other = get_user_model().objects.create_user(username='writer-b', password='x')
        tech = Category.objects.create(name='技术2', slug='tech2')
        for i in range(3):
            Article.objects.create(
                title=f'甲{i}',
                slug=f'jia-{i}',
                publish_time=timezone.now(),
                author=user,
                is_published=True,
            )
        for i in range(2):
            Article.objects.create(
                title=f'乙{i}',
                slug=f'yi-{i}',
                publish_time=timezone.now(),
                author=other,
                category=tech,
                is_published=True,
            )
        Article.objects.create(
            title='乙的草稿',
            slug='yi-draft',
            publish_time=timezone.now(),
            author=other,
            is_published=False,
        )
        return {'a': user, 'b': other, 'tech': tech}

    def test_art_011_filter_by_author(self, api_client, two_authors):
        """ART-011 按作者过滤只返回该作者的文章。"""
        author_id = two_authors['b'].id
        response = api_client.get(f'/api/v1/articles/?author={author_id}')

        assert response.status_code == 200
        data = response.json()['data']
        assert data['total'] == 2
        assert {item['slug'] for item in data['items']} == {'yi-0', 'yi-1'}

    def test_art_012_filter_by_author_excludes_draft(self, api_client, two_authors):
        """ART-012 author 参数不能绕过「仅已发布」：别人的草稿依然看不到。"""
        author_id = two_authors['b'].id
        data = api_client.get(f'/api/v1/articles/?author={author_id}').json()['data']

        assert 'yi-draft' not in {item['slug'] for item in data['items']}

    def test_art_013_filter_by_unknown_author_is_empty(self, api_client, two_authors):
        """ART-013 不存在的作者返回空列表（不是 404：筛选器失效不该让页面报错）。"""
        response = api_client.get('/api/v1/articles/?author=999999')

        assert response.status_code == 200
        data = response.json()['data']
        assert data['items'] == []
        assert data['total'] == 0

    def test_art_014_filter_by_author_and_category(self, api_client, two_authors):
        """ART-014 author 与 category_slug 是「与」关系。"""
        author_id = two_authors['b'].id
        hit = api_client.get(f'/api/v1/articles/?author={author_id}&category_slug=tech2')
        miss = api_client.get(f'/api/v1/articles/?author={author_id}&category_slug=tech')

        assert hit.json()['data']['total'] == 2
        assert miss.json()['data']['total'] == 0

    def test_art_015_invalid_author_param(self, api_client, two_authors):
        """ART-015 author=0 / 非数字 → 422（由 Query(ge=1) 拦）。"""
        assert api_client.get('/api/v1/articles/?author=0').status_code == 422
        assert api_client.get('/api/v1/articles/?author=abc').status_code == 422

    def test_art_016_cache_key_isolated_by_author(self, api_client, two_authors):
        """ART-016 缓存键含 author：连续查两个作者不得串结果。

        这是最容易漏的一处回归——cached_public 只认字符串键，
        键里少一个维度就会把上一次的列表连同 total 一起返回。
        """
        a_id = two_authors['a'].id
        b_id = two_authors['b'].id

        first = api_client.get(f'/api/v1/articles/?author={a_id}').json()['data']
        second = api_client.get(f'/api/v1/articles/?author={b_id}').json()['data']
        again = api_client.get(f'/api/v1/articles/?author={a_id}').json()['data']

        assert first['total'] == 3
        assert second['total'] == 2
        assert again['total'] == 3
        assert {i['slug'] for i in again['items']} == {i['slug'] for i in first['items']}

    def test_art_017_rejects_illegal_slug(self, api_client, two_authors):
        """ART-017 slug 入参白名单：冒号会让不同查询撞同一个缓存键。"""
        response = api_client.get('/api/v1/articles/?category_slug=x:y')

        assert response.status_code == 422
        assert '取值非法' in response.json()['message']
        # 合法 slug 不受影响
        assert api_client.get('/api/v1/articles/?category_slug=tech2').status_code == 200

    def test_art_018_page_upper_bound(self, api_client):
        """ART-018 page 有上限（防 ?page=99999 变成大 OFFSET 慢查询）。"""
        assert api_client.get('/api/v1/articles/?page=501').status_code == 422
        assert api_client.get('/api/v1/articles/?page=500').status_code == 200

    def test_art_019_out_carries_author(self, api_client, two_authors):
        """ART-019 列表出参带 author_id / author_name（卡片要显示谁写的）。"""
        data = api_client.get('/api/v1/articles/?page_size=100').json()['data']
        item = next(i for i in data['items'] if i['slug'] == 'yi-0')

        assert item['author_id'] == two_authors['b'].id
        assert item['author_name'] == 'writer-b'
