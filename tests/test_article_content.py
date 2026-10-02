"""Markdown 正文：创建/更新/详情渲染/预览/长度与最终态校验。"""
from urllib.parse import urlencode

import pytest
from django.utils import timezone

from articles.models import Article


def _create(api_client, auth_header, test_image, **extra):
    """创建文章（封面必填，附件可选）。"""
    payload = {
        'title': '带正文的文章',
        'publish_time': '2026-08-09T14:00:00Z',
        'cover': test_image,
    }
    payload.update(extra)
    return api_client.post('/api/v1/admin/articles/', payload, **auth_header)


@pytest.mark.django_db
class TestCreateWithContent:
    def test_create_content_without_attachment(self, api_client, auth_header, test_image):
        """正文为主：不传附件也能创建，file_url 为 null。"""
        response = _create(api_client, auth_header, test_image, content='# 标题\n\n正文')

        assert response.status_code == 201
        data = response.json()['data']
        assert data['file_url'] is None
        assert data['file_name'] == ''
        assert Article.objects.get(slug=data['slug']).content == '# 标题\n\n正文'

    def test_create_requires_content_or_attachment(self, api_client, auth_header, test_image):
        """正文与附件皆空 -> 400。"""
        response = _create(api_client, auth_header, test_image, content='   ')

        assert response.status_code == 400
        assert '至少填写一项' in response.json()['message']

    def test_create_content_too_long(self, api_client, auth_header, test_image, settings):
        """正文超过上限 -> 400（不依赖 ninja Form 的 max_length）。"""
        settings.ARTICLE_CONTENT_MAX_CHARS = 10

        response = _create(api_client, auth_header, test_image, content='x' * 11)

        assert response.status_code == 400
        assert '正文过长' in response.json()['message']

    def test_create_with_attachment_only_still_works(
        self, api_client, auth_header, test_image, test_pdf
    ):
        """旧行为保留：只传附件（无正文）仍可创建。"""
        response = _create(api_client, auth_header, test_image, attachment=test_pdf)

        assert response.status_code == 201
        assert response.json()['data']['file_url']


@pytest.mark.django_db
class TestDetailRendering:
    def _published(self, user, content: str) -> Article:
        article = Article.objects.create(
            title='渲染测试',
            slug='render-test',
            content=content,
            publish_time=timezone.now(),
            author=user,
            is_published=True,
        )
        return article

    def test_public_detail_returns_sanitized_html(self, api_client, user):
        """公开详情返回消毒后的 content_html，不返回原始 Markdown。"""
        self._published(user, '# 标题\n\n**加粗**')

        response = api_client.get('/api/v1/articles/render-test/')

        assert response.status_code == 200
        data = response.json()['data']
        assert '<h1>标题</h1>' in data['content_html']
        assert '<strong>加粗</strong>' in data['content_html']
        assert 'content' not in data

    def test_admin_detail_returns_raw_markdown(self, api_client, auth_header, user):
        """管理详情额外返回原始 Markdown，供编辑回填。"""
        article = self._published(user, '# 标题')

        response = api_client.get(f'/api/v1/admin/articles/{article.id}/', **auth_header)

        assert response.status_code == 200
        assert response.json()['data']['content'] == '# 标题'

    def test_empty_content_html(self, api_client, auth_header, user):
        """正文为空时 content_html 为空串（前端走附件回退）。"""
        article = Article.objects.create(
            title='无正文', slug='no-content', publish_time=timezone.now(), author=user,
            is_published=True,
        )

        response = api_client.get(f'/api/v1/articles/{article.slug}/')

        assert response.json()['data']['content_html'] == ''


@pytest.mark.django_db
class TestSanitize:
    MARKDOWN = (
        '# 标题\n\n'
        '<script>alert(1)</script>\n\n'
        '<img src="/media/inline/abc.webp" onerror="alert(1)" alt="图">\n\n'
        '[外链](https://example.com)  [危险](javascript:alert(1))\n\n'
        '| a | b |\n|:--|--:|\n| 1 | 2 |\n\n'
        '```python\nprint(1)\n```\n'
    )

    def _html(self) -> str:
        from articles.rendering import render_markdown

        return render_markdown(self.MARKDOWN)

    def test_scripts_and_handlers_stripped(self, user):
        html = self._html()
        assert '<script' not in html
        assert 'onerror' not in html
        assert 'javascript:' not in html

    def test_relative_image_preserved_and_lazy(self, user):
        """相对路径图片不被剥掉，且注入懒加载属性（nh3 实测保留）。"""
        html = self._html()
        assert 'src="/media/inline/abc.webp"' in html
        assert 'loading="lazy"' in html
        assert 'decoding="async"' in html

    def test_external_link_gets_target_and_rel(self, user):
        html = self._html()
        assert 'href="https://example.com"' in html
        assert 'target="_blank"' in html
        assert 'rel="noopener noreferrer"' in html

    def test_table_align_and_code_class(self, user):
        html = self._html()
        assert 'align="left"' in html
        assert 'align="right"' in html
        assert 'class="language-python"' in html


@pytest.mark.django_db
class TestPreviewEndpoint:
    def test_preview_renders(self, api_client, auth_header):
        response = api_client.post(
            '/api/v1/admin/articles/preview/',
            data='{"content": "## 预览"}',
            content_type='application/json',
            **auth_header,
        )

        assert response.status_code == 200
        assert '<h2>预览</h2>' in response.json()['data']['content_html']

    def test_preview_route_not_shadowed(self, api_client, auth_header):
        """preview 是单段路径，必须注册在 /articles/{article_id}/ 之前。"""
        response = api_client.post(
            '/api/v1/admin/articles/preview/',
            data='{"content": "x"}',
            content_type='application/json',
            **auth_header,
        )

        assert response.status_code == 200

    def test_preview_too_long(self, api_client, auth_header, settings):
        settings.ARTICLE_CONTENT_MAX_CHARS = 5

        response = api_client.post(
            '/api/v1/admin/articles/preview/',
            data='{"content": "123456"}',
            content_type='application/json',
            **auth_header,
        )

        assert response.status_code == 400


@pytest.mark.django_db
class TestUpdateContent:
    def _article(self, user, *, content: str = '', slug: str = 'upd') -> Article:
        return Article.objects.create(
            title='更新', slug=slug, content=content,
            publish_time=timezone.now(), author=user,
        )

    def test_update_content(self, api_client, auth_header, user):
        article = self._article(user)

        response = api_client.put(
            f'/api/v1/admin/articles/{article.id}/',
            urlencode({'content': '新正文'}),
            content_type='application/x-www-form-urlencoded',
            **auth_header,
        )

        assert response.status_code == 200
        article.refresh_from_db()
        assert article.content == '新正文'

    def test_clear_content_without_attachment_rejected(self, api_client, auth_header, user):
        """清空正文且无附件 -> 400（防止产出空文章）。"""
        article = self._article(user, content='有正文')

        response = api_client.put(
            f'/api/v1/admin/articles/{article.id}/',
            urlencode({'content': ''}),
            content_type='application/x-www-form-urlencoded',
            **auth_header,
        )

        assert response.status_code == 400
        assert '至少填写一项' in response.json()['message']

    def test_metadata_only_update_not_blocked(self, api_client, auth_header, user):
        """只改标题（不提交正文/附件）不应被最终态校验误判。"""
        article = self._article(user)

        response = api_client.put(
            f'/api/v1/admin/articles/{article.id}/',
            urlencode({'title': '新标题'}),
            content_type='application/x-www-form-urlencoded',
            **auth_header,
        )

        assert response.status_code == 200
        article.refresh_from_db()
        assert article.title == '新标题'
