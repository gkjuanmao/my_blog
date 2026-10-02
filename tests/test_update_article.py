"""文章管理接口测试：PUT /api/v1/admin/articles/{article_id}/（更新）。

覆盖编辑文章时各字段与文件的更新行为：
- 标量字段能否真正改掉（含置空与布尔假值）、未传字段是否保持原值
- 替换封面/附件后文件是否落盘、返回的 URL 是否指向真实文件、旧文件是否清理
- auto_now 的 updated_at 是否随更新推进

回归背景：该接口原先用 QuerySet.update() 写库，绕过了 Model.save() 的
FileField.pre_save()，导致上传的文件不落盘、字段被存成客户端原始文件名
（cover_image='photo.jpg'），cover_image_url 变成 /media/photo.jpg 指向不存在的
文件 -> 编辑页重新上传封面后图片 404。auto_now 的 updated_at 同样不刷新。
"""
import io
import json
from datetime import timedelta
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart
from django.utils import timezone
from PIL import Image

from articles.models import Article, Category, Tag


def make_image(name: str, color: str = 'blue') -> SimpleUploadedFile:
    """生成一张上传图片，编码格式与扩展名一致（.png → PNG，其余 → JPEG）。

    必须匹配扩展名：上传侧现在会校验「实际格式 vs 扩展名」，不匹配直接 400
    （原先只查扩展名白名单，所以这里曾经能塞 JPEG 字节进 .png 而不报错）。
    """
    image = Image.new('RGB', (30, 30), color=color)
    buffer = io.BytesIO()
    fmt = 'PNG' if name.lower().endswith('.png') else 'JPEG'
    image.save(buffer, format=fmt)
    buffer.seek(0)
    return SimpleUploadedFile(name, buffer.read(), content_type=f'image/{fmt.lower()}')


def make_pdf(name: str = 'attachment.pdf') -> SimpleUploadedFile:
    """生成一个最小 PDF 上传文件。"""
    return SimpleUploadedFile(
        name, b'%PDF-1.4\n' + b'x' * 2048, content_type='application/pdf'
    )


def media_file(url: str, media_root: Path) -> Path:
    """把 /media/... 相对 URL 映射为 MEDIA_ROOT 下的真实路径。"""
    assert url.startswith('/media/'), f'{url!r} 应是 /media/ 开头的相对路径'
    return Path(media_root, url.removeprefix('/media/'))


def put_article(api_client, auth_header, article_id: int, data: dict):
    """以 multipart 提交更新，与前端 FormData 的编码方式一致。

    注意：Django 6 测试客户端的 put() 不做 multipart 编码（只有 post() 会走
    _encode_data），直接传 dict 会被 str() 化成非法的 body，因此这里手工用
    encode_multipart 编码，并带上含 boundary 的 content_type。
    """
    return api_client.put(
        f'/api/v1/admin/articles/{article_id}/',
        encode_multipart(BOUNDARY, data),
        content_type=MULTIPART_CONTENT,
        **auth_header,
    )


@pytest.fixture
def other_category_and_tag():
    """额外一组分类/标签，用于验证改挂与替换。"""
    return Category.objects.create(name='旅行', slug='travel'), Tag.objects.create(
        name='云南', slug='yunnan'
    )


@pytest.fixture
def created(api_client, auth_header):
    """经创建接口造一篇文章（封面/附件均已正常落盘），返回创建响应的 data。"""
    response = api_client.post(
        '/api/v1/admin/articles/',
        {
            'title': '原标题',
            'slug': 'origin',
            'summary': '原摘要',
            'location': '原地点',
            'publish_time': '2026-08-09T14:00:00Z',
            'is_published': True,
            'cover': make_image('old-cover.jpg', 'red'),
            'attachment': make_pdf('old-file.pdf'),
        },
        **auth_header,
    )
    assert response.status_code == 201
    return response.json()['data']


@pytest.mark.django_db
class TestUpdateArticleScalarFieldsAPI:
    def test_adm_056_all_scalar_fields_updated(
        self, api_client, auth_header, created, other_category_and_tag
    ):
        """ADM-056 一次提交改掉全部标量字段。"""
        category, tag = other_category_and_tag
        response = put_article(
            api_client,
            auth_header,
            created['id'],
            {
                'title': '新标题',
                'summary': '新摘要',
                'location': '新地点',
                'publish_time': '2026-09-01T10:30:00',
                'is_published': 'false',
                'category_id': str(category.id),
                'tag_ids': json.dumps([tag.id]),
            },
        )

        assert response.status_code == 200
        article = Article.objects.get(pk=created['id'])
        assert article.title == '新标题'
        assert article.summary == '新摘要'
        assert article.location == '新地点'
        assert article.category_id == category.id
        assert list(article.tags.values_list('id', flat=True)) == [tag.id]
        assert timezone.localtime(article.publish_time).strftime('%Y-%m-%d %H:%M') == (
            '2026-09-01 10:30'
        )

    def test_adm_057_unpublish(self, api_client, auth_header, created):
        """ADM-057 已发布可改为草稿（布尔假值必须生效）。"""
        assert Article.objects.get(pk=created['id']).is_published is True

        response = put_article(api_client, auth_header, created['id'], {'is_published': 'false'})

        assert response.status_code == 200
        assert Article.objects.get(pk=created['id']).is_published is False
        assert response.json()['data']['is_published'] is False

    def test_adm_058_clear_summary_and_location(self, api_client, auth_header, created):
        """ADM-058 摘要与地点可清空为空串。"""
        response = put_article(
            api_client, auth_header, created['id'], {'summary': '', 'location': ''}
        )

        assert response.status_code == 200
        article = Article.objects.get(pk=created['id'])
        assert article.summary == ''
        assert article.location == ''

    def test_adm_059_partial_update_keeps_other_fields(self, api_client, auth_header, created):
        """ADM-059 只传 title 时其余字段保持原值。"""
        response = put_article(api_client, auth_header, created['id'], {'title': '仅改标题'})

        assert response.status_code == 200
        article = Article.objects.get(pk=created['id'])
        assert article.title == '仅改标题'
        assert article.summary == '原摘要'
        assert article.location == '原地点'
        assert article.is_published is True
        assert article.cover_image_name == 'old-cover.jpg'
        assert article.file_name == 'old-file.pdf'

    def test_adm_060_updated_at_advances(self, api_client, auth_header, created):
        """ADM-060 更新后 updated_at 必须推进（auto_now 语义）。"""
        past = timezone.now() - timedelta(days=1)
        Article.objects.filter(pk=created['id']).update(updated_at=past)

        response = put_article(api_client, auth_header, created['id'], {'title': '触发更新时间'})

        assert response.status_code == 200
        article = Article.objects.get(pk=created['id'])
        assert article.updated_at > past, 'updated_at 未随更新推进'

    def test_adm_061_tag_ids_replaces_not_appends(
        self, api_client, auth_header, created, other_category_and_tag
    ):
        """ADM-061 标签为整体替换而非追加。"""
        _, tag = other_category_and_tag
        before = list(Article.objects.get(pk=created['id']).tags.values_list('id', flat=True))
        assert before and tag.id not in before

        response = put_article(
            api_client, auth_header, created['id'], {'tag_ids': json.dumps([tag.id])}
        )

        assert response.status_code == 200
        article = Article.objects.get(pk=created['id'])
        assert list(article.tags.values_list('id', flat=True)) == [tag.id]

    def test_adm_062_category_not_found(self, api_client, auth_header, created):
        """ADM-062 传不存在的 category_id 返回 400 且不改动数据。"""
        response = put_article(api_client, auth_header, created['id'], {'category_id': '999'})

        assert response.status_code == 400
        assert '分类不存在' in response.json()['message']
        assert Article.objects.get(pk=created['id']).title == '原标题'


@pytest.mark.django_db
class TestUpdateArticleFilesAPI:
    def test_adm_063_replace_cover_stores_file_and_url_resolves(
        self, api_client, auth_header, created, media_root
    ):
        """ADM-063 替换封面：新文件落盘、DB 存 covers/ 路径、URL 指向真实文件。"""
        old_storage_name = Article.objects.get(pk=created['id']).cover_image.name

        response = put_article(
            api_client, auth_header, created['id'], {'cover': make_image('new-cover.jpg', 'green')}
        )

        assert response.status_code == 200
        data = response.json()['data']
        article = Article.objects.get(pk=created['id'])

        assert article.cover_image_name == 'new-cover.jpg'
        assert article.cover_image.name.startswith('covers/')
        assert article.cover_image.name != old_storage_name
        assert data['cover_image_url'] == article.cover_image.url
        assert media_file(data['cover_image_url'], media_root).is_file(), (
            f"封面 URL {data['cover_image_url']} 未指向真实文件"
        )

    def test_adm_064_replace_cover_removes_old_file(
        self, api_client, auth_header, created, media_root
    ):
        """ADM-064 替换封面后旧文件被清理，不留孤儿。"""
        old_path = media_file(created['cover_image_url'], media_root)
        assert old_path.is_file()

        response = put_article(
            api_client, auth_header, created['id'], {'cover': make_image('new-cover.jpg')}
        )

        assert response.status_code == 200
        assert not old_path.exists(), '替换封面后旧文件仍残留'

    def test_adm_065_replace_attachment(self, api_client, auth_header, created, media_root):
        """ADM-065 替换附件：新文件落盘、URL 指向真实文件、旧文件被清理。"""
        old_path = media_file(created['file_url'], media_root)
        assert old_path.is_file()

        response = put_article(
            api_client, auth_header, created['id'], {'attachment': make_pdf('new-file.pdf')}
        )

        assert response.status_code == 200
        data = response.json()['data']
        article = Article.objects.get(pk=created['id'])

        assert article.file_name == 'new-file.pdf'
        assert article.file.name.startswith('files/')
        assert media_file(data['file_url'], media_root).is_file()
        assert not old_path.exists(), '替换附件后旧文件仍残留'

    def test_adm_066_keep_files_when_not_provided(
        self, api_client, auth_header, created, media_root
    ):
        """ADM-066 不传文件时保留原封面与附件（文件也不应被删除）。"""
        cover_path = media_file(created['cover_image_url'], media_root)
        file_path = media_file(created['file_url'], media_root)

        response = put_article(api_client, auth_header, created['id'], {'title': '不改文件'})

        assert response.status_code == 200
        article = Article.objects.get(pk=created['id'])
        assert article.cover_image_name == 'old-cover.jpg'
        assert article.file_name == 'old-file.pdf'
        assert cover_path.is_file()
        assert file_path.is_file()

    def test_adm_067_replace_both_files(self, api_client, auth_header, created, media_root):
        """ADM-067 同时替换封面与附件。"""
        response = put_article(
            api_client,
            auth_header,
            created['id'],
            {
                'cover': make_image('both-cover.png', 'purple'),
                'attachment': make_pdf('both-file.pdf'),
            },
        )

        assert response.status_code == 200
        data = response.json()['data']
        assert data['cover_image_name'] == 'both-cover.png'
        assert data['file_name'] == 'both-file.pdf'
        assert media_file(data['cover_image_url'], media_root).is_file()
        assert media_file(data['file_url'], media_root).is_file()

    def test_adm_068_invalid_cover_keeps_old(
        self, api_client, auth_header, created, media_root
    ):
        """ADM-068 新封面格式非法时返回 400，原封面文件与字段均不被破坏。"""
        old_path = media_file(created['cover_image_url'], media_root)
        old_storage_name = Article.objects.get(pk=created['id']).cover_image.name
        bad_file = SimpleUploadedFile(
            'bad.exe', b'MZ' + b'x' * 100, content_type='application/octet-stream'
        )

        response = put_article(api_client, auth_header, created['id'], {'cover': bad_file})

        assert response.status_code == 400
        article = Article.objects.get(pk=created['id'])
        assert article.cover_image.name == old_storage_name
        assert article.cover_image_name == 'old-cover.jpg'
        assert old_path.is_file()

    def test_adm_069_form_like_payload_with_new_cover(
        self, api_client, auth_header, created, media_root, other_category_and_tag
    ):
        """ADM-069 复刻前端编辑表单提交（全部字段 + 新封面）：封面生效且图片可访问。"""
        category, tag = other_category_and_tag
        response = put_article(
            api_client,
            auth_header,
            created['id'],
            {
                'title': '编辑后的标题',
                'slug': 'origin',
                'summary': '编辑后的摘要',
                'location': '编辑后的地点',
                'publish_time': '2026-09-02T08:00:00',
                'category_id': str(category.id),
                'tag_ids': json.dumps([tag.id]),
                'is_published': 'true',
                'cover': make_image('form-cover.jpg', 'orange'),
            },
        )

        assert response.status_code == 200
        data = response.json()['data']
        article = Article.objects.get(pk=created['id'])

        assert article.title == '编辑后的标题'
        assert article.location == '编辑后的地点'
        assert article.category_id == category.id
        assert article.cover_image_name == 'form-cover.jpg'
        assert article.cover_image.name.startswith('covers/')
        assert media_file(data['cover_image_url'], media_root).is_file()
        # 未提交附件的表单不应破坏原附件
        assert media_file(data['file_url'], media_root).is_file()
