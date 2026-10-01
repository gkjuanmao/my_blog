"""归档导入：往返保真、幂等、字段规则、回滚包。"""
import hashlib
import io
import json
import zipfile

import pytest
from django.utils import timezone

from articles.models import Article, Category, Tag
from articles.utils import generate_slug

pytestmark = pytest.mark.django_db

EXPORT_URL = '/api/v1/admin/articles/export/'
STAGE_URL = '/api/v1/admin/articles/import/stage/'
COMMIT_URL = '/api/v1/admin/articles/import/commit/'


def export_zip(api_client, staff_header, ids, zip_bytes):
    """走真实接口导出，返回 zip 字节。"""
    data = api_client.get(f'{EXPORT_URL}?ids={ids}', **staff_header).json()['data']
    return zip_bytes(api_client.get(data['download_url']))


def stage(api_client, staff_header, payload: bytes, strategy='skip'):
    """第一阶段：上传压缩包。"""
    from django.core.files.uploadedfile import SimpleUploadedFile

    response = api_client.post(
        STAGE_URL,
        {
            'file': SimpleUploadedFile('pkg.zip', payload, content_type='application/zip'),
            'strategy': strategy,
        },
        **staff_header,
    )
    assert response.status_code == 200, response.json()
    return response


def commit(api_client, staff_header, staged_id, **options):
    """第二阶段：执行导入。"""
    body = {'staged_id': staged_id, 'strategy': 'skip', **options}
    return api_client.post(COMMIT_URL, body, content_type='application/json', **staff_header)


def handcrafted_zip(make_zip, jpeg, *, article_json: dict, attachment=b'%PDF-1.4 x'):
    """手工构造一个最小可导入包（用于精确控制 article.json）。"""
    return make_zip({
        'articles/001-x/article.json': json.dumps(article_json, ensure_ascii=False).encode(),
        'articles/001-x/cover.jpg': jpeg,
        'articles/001-x/attachment.pdf': attachment,
    })


@pytest.fixture
def package(make_zip, jpeg_factory):
    """一个合法的默认包（只需状态、不关心内容的用例用）。"""
    return handcrafted_zip(
        make_zip,
        jpeg_factory(),
        article_json={
            'title': '重新预检用例',
            'slug': 'replan-pkg',
            'publish_time': timezone.now().isoformat(),
            'cover': {'file': 'cover.jpg'},
            'attachment': {'file': 'attachment.pdf'},
        },
    )


@pytest.fixture
def archive_settings(settings):
    """归档测试设置：导入间隔置 0（同一测试内可连续导入）。"""
    settings.ARCHIVE_IMPORT_MIN_INTERVAL_SECONDS = 0
    settings.ARCHIVE_STAGING_TTL_SECONDS = 600
    settings.ARCHIVE_TICKET_TTL_SECONDS = 600
    return settings


# --------------------------------------------------------------------------- 往返保真


class TestRoundTrip:
    def test_export_import_roundtrip_preserves_content(
        self,
        api_client,
        staff_header,
        staff_user,
        jpeg_factory,
        article_factory,
        archive_settings,
        zip_bytes,
    ):
        category = Category.objects.create(name='境外游', slug='overseas')
        tag = Tag.objects.create(name='摄影', slug='photo')
        cover = jpeg_factory(size=(60, 40), color='blue')
        article = article_factory(
            staff_user, slug='roundtrip', title='往返游记', cover_bytes=cover
        )
        article.summary = '原始摘要'
        article.location = '伊斯坦布尔'
        article.category = category
        article.is_published = True
        article.views = 999
        article.save()
        article.tags.set([tag])

        payload = export_zip(api_client, staff_header, article.id, zip_bytes)

        # 删掉原文章（post_delete 会清掉媒体文件），再导入
        article.delete()
        assert Article.objects.count() == 0

        staged = stage(api_client, staff_header, payload)
        assert staged.status_code == 200, staged.json()
        dry = staged.json()['data']
        assert dry['dry_run'] is True
        assert dry['totals']['create'] == 1
        assert dry['items'][0]['action'] == 'create'

        result = commit(api_client, staff_header, dry['staged_id'])
        assert result.status_code == 200, result.json()
        report = result.json()['data']
        assert report['dry_run'] is False
        assert report['totals']['create'] == 1
        assert report['totals']['failed'] == 0

        restored = Article.objects.get(slug='roundtrip')
        assert restored.title == '往返游记'
        assert restored.summary == '原始摘要'
        assert restored.location == '伊斯坦布尔'
        assert restored.is_published is True
        assert restored.category.slug == 'overseas'
        assert [t.slug for t in restored.tags.all()] == ['photo']
        # views / 时间戳不恢复（D3）
        assert restored.views == 0
        # 封面被服务端重编码过，但哈希列记录的是**源字节**
        assert restored.cover_image_sha256 == hashlib.sha256(cover).hexdigest()

    def test_cover_is_reencoded_and_exif_stripped(
        self,
        api_client,
        staff_header,
        staff_user,
        jpeg_factory,
        article_factory,
        archive_settings,
        zip_bytes,
    ):
        """D20：封面重编码 + exif_transpose（Orientation=6 会转置尺寸）。"""
        cover = jpeg_factory(size=(60, 40), orientation=6)
        article = article_factory(staff_user, slug='exif-case', cover_bytes=cover)
        payload = export_zip(api_client, staff_header, article.id, zip_bytes)
        article.delete()

        dry = stage(api_client, staff_header, payload).json()['data']
        report = commit(api_client, staff_header, dry['staged_id']).json()['data']

        restored = Article.objects.get(slug='exif-case')
        from PIL import Image

        with restored.cover_image.open('rb') as handle:
            image = Image.open(handle)
            assert image.size == (40, 60)  # orientation=6 → 旋转后宽高互换
            assert not image.getexif()
        assert any('EXIF' in w for w in report['items'][0]['warnings'])

    def test_no_exif_warning_when_orientation_absent(
        self,
        api_client,
        staff_header,
        staff_user,
        jpeg_factory,
        article_factory,
        archive_settings,
        zip_bytes,
    ):
        """Pillow 12.x 在无 Orientation 时 exif_transpose 也返回副本 →
        告警必须看标签值，否则每张封面都会假阳性报警。"""
        article = article_factory(
            staff_user, slug='no-exif', cover_bytes=jpeg_factory()
        )
        payload = export_zip(api_client, staff_header, article.id, zip_bytes)
        article.delete()

        dry = stage(api_client, staff_header, payload).json()['data']
        report = commit(api_client, staff_header, dry['staged_id']).json()['data']

        assert not any('EXIF' in w for w in report['items'][0]['warnings'])


    def test_canonical_cover_is_stored_byte_identical(
        self, api_client, staff_header, jpeg_factory, archive_settings, make_zip
    ):
        """规范格式的封面必须**原样存储**（否则导出出去的字节永不等于记录的哈希）。"""
        cover = jpeg_factory()
        payload = handcrafted_zip(
            make_zip,
            cover,
            article_json={
                'title': '原样存储',
                'slug': 'canonical-cover',
                'publish_time': timezone.now().isoformat(),
                'cover': {'file': 'cover.jpg'},
                'attachment': {'file': 'attachment.pdf'},
            },
        )
        dry = stage(api_client, staff_header, payload).json()['data']
        report = commit(api_client, staff_header, dry['staged_id']).json()['data']

        created = Article.objects.get(slug='canonical-cover')
        with created.cover_image.open('rb') as handle:
            assert handle.read() == cover
        assert created.cover_image_sha256 == hashlib.sha256(cover).hexdigest()
        assert not any('重编码' in w for w in report['items'][0]['warnings'])

    def test_reexport_then_import_update_does_not_rewrite_media(
        self,
        api_client,
        staff_header,
        staff_user,
        jpeg_factory,
        article_factory,
        archive_settings,
        zip_bytes,
    ):
        """回归：导出 → 导入(update) 不得重写媒体。

        曾因「无条件重编码 + 源字节哈希」的组合，使得
        导出 → 导入 → 导出 → 导入 每一轮都重写并再次损失画质。
        """
        article = article_factory(
            staff_user, slug='roundtrip-idem', cover_bytes=jpeg_factory()
        )
        payload = export_zip(api_client, staff_header, article.id, zip_bytes)
        article.delete()
        dry = stage(api_client, staff_header, payload).json()['data']
        commit(api_client, staff_header, dry['staged_id'])

        created = Article.objects.get(slug='roundtrip-idem')
        cover_name = created.cover_image.name
        cover_sha = created.cover_image_sha256
        file_name = created.file.name

        # 再导出（导出的是"存储字节"）并用 update 导回：必须完全不动
        payload2 = export_zip(api_client, staff_header, created.id, zip_bytes)
        dry2 = stage(api_client, staff_header, payload2, strategy='update').json()['data']
        commit(api_client, staff_header, dry2['staged_id'], strategy='update')

        created.refresh_from_db()
        assert created.cover_image.name == cover_name
        assert created.file.name == file_name
        assert created.cover_image_sha256 == cover_sha


# --------------------------------------------------------------------------- 策略与幂等


class TestStrategies:
    def _prepare(
        self, api_client, staff_header, staff_user, jpeg_factory, article_factory, zip_bytes
    ):
        article = article_factory(
            staff_user, slug='strategy-case', title='原标题', cover_bytes=jpeg_factory()
        )
        payload = export_zip(api_client, staff_header, article.id, zip_bytes)
        return article, payload

    def test_skip_leaves_existing_untouched(
        self,
        api_client,
        staff_header,
        staff_user,
        jpeg_factory,
        article_factory,
        archive_settings,
        zip_bytes,
    ):
        article, payload = self._prepare(
            api_client, staff_header, staff_user, jpeg_factory, article_factory, zip_bytes
        )
        dry = stage(api_client, staff_header, payload).json()['data']
        assert dry['items'][0]['action'] == 'skip'
        report = commit(api_client, staff_header, dry['staged_id']).json()['data']
        assert report['totals']['skip'] == 1
        assert Article.objects.get(pk=article.pk).title == '原标题'

    def test_update_twice_is_idempotent(
        self,
        api_client,
        staff_header,
        staff_user,
        jpeg_factory,
        article_factory,
        archive_settings,
        zip_bytes,
    ):
        """update 连导两次：字段与文件集合不变（updated_at 除外）。"""
        article, payload = self._prepare(
            api_client, staff_header, staff_user, jpeg_factory, article_factory, zip_bytes
        )

        first = stage(api_client, staff_header, payload, strategy='update').json()['data']
        assert first['items'][0]['action'] == 'update'
        assert (
            commit(api_client, staff_header, first['staged_id'], strategy='update').status_code
            == 200
        )

        article.refresh_from_db()
        cover_name = article.cover_image.name
        file_name = article.file.name

        second = stage(api_client, staff_header, payload, strategy='update').json()['data']
        assert (
            commit(api_client, staff_header, second['staged_id'], strategy='update').status_code
            == 200
        )

        article.refresh_from_db()
        # 源字节哈希相同 → 不重写媒体（幂等键生效）
        assert article.cover_image.name == cover_name
        assert article.file.name == file_name

    def test_update_only_touches_present_keys(
        self,
        api_client,
        staff_header,
        staff_user,
        jpeg_factory,
        article_factory,
        archive_settings,
        make_zip,
    ):
        """键缺失不改、显式 null 才清空、views 绝不被覆盖。"""
        article = article_factory(
            staff_user, slug='fields-case', title='原标题', cover_bytes=jpeg_factory()
        )
        article.summary = '原摘要'
        article.location = '原地'
        article.views = 42
        article.save()

        payload = handcrafted_zip(
            make_zip,
            jpeg_factory(),
            article_json={
                'schema': 'myblog.article/v1',
                'title': '新标题',
                'slug': 'fields-case',
                'summary': None,  # 显式 null → 清空
                'publish_time': timezone.now().isoformat(),
                'cover': {'file': 'cover.jpg'},
                'attachment': {'file': 'attachment.pdf'},
                'import': {'action': 'update'},
            },
        )

        dry = stage(api_client, staff_header, payload).json()['data']
        assert dry['items'][0]['action'] == 'update'
        commit(api_client, staff_header, dry['staged_id'])

        article.refresh_from_db()
        assert article.title == '新标题'
        assert article.summary == ''  # 显式 null 清空
        assert article.location == '原地'  # 键缺失 → 不动
        assert article.views == 42  # 永不覆盖

    def test_as_draft_only_applies_to_create(
        self,
        api_client,
        staff_header,
        staff_user,
        jpeg_factory,
        article_factory,
        archive_settings,
        zip_bytes,
    ):
        """D22：as_draft 不作用于 update，且会在报告里告警。"""
        article, payload = self._prepare(
            api_client, staff_header, staff_user, jpeg_factory, article_factory, zip_bytes
        )
        assert article.is_published is True

        dry = stage(api_client, staff_header, payload, strategy='update').json()['data']
        report = commit(
            api_client, staff_header, dry['staged_id'], strategy='update', as_draft=True
        ).json()['data']

        article.refresh_from_db()
        assert article.is_published is True  # 没有被静默下架
        assert any('草稿' in w for w in report['items'][0]['warnings'])

    def test_as_draft_applies_to_create(
        self, api_client, staff_header, jpeg_factory, archive_settings, make_zip
    ):
        payload = handcrafted_zip(
            make_zip,
            jpeg_factory(),
            article_json={
                'title': '应成为草稿',
                'slug': 'draft-on-create',
                'publish_time': timezone.now().isoformat(),
                'is_published': True,
                'cover': {'file': 'cover.jpg'},
                'attachment': {'file': 'attachment.pdf'},
            },
        )
        dry = stage(api_client, staff_header, payload).json()['data']
        commit(api_client, staff_header, dry['staged_id'], as_draft=True)
        assert Article.objects.get(slug='draft-on-create').is_published is False

    def test_category_and_tags_are_created(
        self, api_client, staff_header, jpeg_factory, archive_settings, make_zip
    ):
        payload = handcrafted_zip(
            make_zip,
            jpeg_factory(),
            article_json={
                'title': '新分类文章',
                'slug': 'taxonomy-case',
                'publish_time': timezone.now().isoformat(),
                'category': {'slug': 'new-cat', 'name': '新分类', 'description': '描述'},
                'tags': [{'slug': 'new-tag', 'name': '新标签'}],
                'cover': {'file': 'cover.jpg'},
                'attachment': {'file': 'attachment.pdf'},
            },
        )
        dry = stage(api_client, staff_header, payload).json()['data']
        assert dry['totals']['categories_to_create'] == ['new-cat']
        assert dry['totals']['tags_to_create'] == ['new-tag']
        commit(api_client, staff_header, dry['staged_id'])

        created = Article.objects.get(slug='taxonomy-case')
        assert created.category.name == '新分类'
        assert [t.slug for t in created.tags.all()] == ['new-tag']

    def test_taxonomy_reuses_existing_without_renaming(
        self, api_client, staff_header, jpeg_factory, archive_settings, make_zip
    ):
        """按 slug 复用已有分类，且绝不改名/改描述。"""
        Category.objects.create(name='既有名', slug='reuse-cat', description='原描述')
        payload = handcrafted_zip(
            make_zip,
            jpeg_factory(),
            article_json={
                'title': '复用分类',
                'slug': 'reuse-case',
                'publish_time': timezone.now().isoformat(),
                'category': {'slug': 'reuse-cat', 'name': '想改成这个名字'},
                'cover': {'file': 'cover.jpg'},
                'attachment': {'file': 'attachment.pdf'},
            },
        )
        dry = stage(api_client, staff_header, payload).json()['data']
        assert dry['totals']['categories_to_create'] == []
        commit(api_client, staff_header, dry['staged_id'])

        assert Category.objects.get(slug='reuse-cat').name == '既有名'
        assert Article.objects.get(slug='reuse-case').category.slug == 'reuse-cat'

    def test_null_category_and_empty_tags_stay_empty(
        self, api_client, staff_header, jpeg_factory, archive_settings, make_zip
    ):
        """D12：category:null / tags:[] 保真，不注入默认分类/标签。"""
        payload = handcrafted_zip(
            make_zip,
            jpeg_factory(),
            article_json={
                'title': '无分类文章',
                'slug': 'null-cat',
                'publish_time': timezone.now().isoformat(),
                'category': None,
                'tags': [],
                'cover': {'file': 'cover.jpg'},
                'attachment': {'file': 'attachment.pdf'},
            },
        )
        dry = stage(api_client, staff_header, payload).json()['data']
        commit(api_client, staff_header, dry['staged_id'])

        created = Article.objects.get(slug='null-cat')
        assert created.category is None
        assert created.tags.count() == 0
        assert not Category.objects.filter(slug='default-category').exists()


# --------------------------------------------------------------------------- 回滚包


class TestRollback:
    def test_update_produces_usable_rollback_package(
        self,
        api_client,
        staff_header,
        staff_user,
        jpeg_factory,
        article_factory,
        archive_settings,
        make_zip,
        zip_bytes,
    ):
        """回滚包必须真的能覆盖回去（内部 action=update，而非 auto）。"""
        article = article_factory(
            staff_user, slug='rollback-case', title='原标题', cover_bytes=jpeg_factory()
        )
        payload = handcrafted_zip(
            make_zip,
            jpeg_factory(color='green'),
            article_json={
                'title': '被改后的标题',
                'slug': 'rollback-case',
                'publish_time': timezone.now().isoformat(),
                'cover': {'file': 'cover.jpg'},
                'attachment': {'file': 'attachment.pdf'},
                'import': {'action': 'update'},
            },
        )

        dry = stage(api_client, staff_header, payload).json()['data']
        report = commit(api_client, staff_header, dry['staged_id']).json()['data']
        assert report['rollback_package'] is not None
        assert report['rollback_package']['count'] == 1
        assert Article.objects.get(pk=article.pk).title == '被改后的标题'

        # 下载回滚包 → 用默认策略（skip）导入也必须真的覆盖回去
        rollback_zip = zip_bytes(api_client.get(report['rollback_package']['download_url']))
        with zipfile.ZipFile(io.BytesIO(rollback_zip)) as zf:
            entry = [n for n in zf.namelist() if n.endswith('/article.json')][0]
            assert json.loads(zf.read(entry))['import']['action'] == 'update'

        rollback_dry = stage(api_client, staff_header, rollback_zip).json()['data']
        assert rollback_dry['items'][0]['action'] == 'update'
        commit(api_client, staff_header, rollback_dry['staged_id'])

        assert Article.objects.get(pk=article.pk).title == '原标题'

    def test_per_item_update_override_triggers_rollback(
        self,
        api_client,
        staff_header,
        staff_user,
        jpeg_factory,
        article_factory,
        archive_settings,
        make_zip,
    ):
        """D9 × D14：全局 strategy=skip + 单篇 action=update 也必须生成回滚包。"""
        article = article_factory(
            staff_user, slug='override-case', title='原标题', cover_bytes=jpeg_factory()
        )
        payload = handcrafted_zip(
            make_zip,
            jpeg_factory(color='green'),
            article_json={
                'title': '被覆盖的标题',
                'slug': 'override-case',
                'publish_time': timezone.now().isoformat(),
                'cover': {'file': 'cover.jpg'},
                'attachment': {'file': 'attachment.pdf'},
                'import': {'action': 'update'},
            },
        )
        dry = stage(api_client, staff_header, payload, strategy='skip').json()['data']
        report = commit(api_client, staff_header, dry['staged_id'], strategy='skip').json()['data']
        assert report['rollback_package'] is not None
        assert Article.objects.get(pk=article.pk).title == '被覆盖的标题'

    def test_create_new_dedupes_identical_content(
        self,
        api_client,
        staff_header,
        staff_user,
        jpeg_factory,
        article_factory,
        archive_settings,
        zip_bytes,
    ):
        """create_new 重试同一包不应产生 -2/-3 副本。"""
        article = article_factory(
            staff_user, slug='dedupe-case', title='去重', cover_bytes=jpeg_factory()
        )
        payload = export_zip(api_client, staff_header, article.id, zip_bytes)

        first = stage(api_client, staff_header, payload, strategy='create_new').json()['data']
        report = commit(
            api_client, staff_header, first['staged_id'], strategy='create_new'
        ).json()['data']
        assert report['items'][0]['action'] == 'skip'
        assert report['items'][0]['skip_reason'] == 'identical'
        assert Article.objects.count() == 1


# --------------------------------------------------------------------------- 暂存重新预检


class TestReplan:
    def test_replan_with_new_strategy_without_reupload(
        self,
        api_client,
        staff_header,
        staff_user,
        jpeg_factory,
        article_factory,
        archive_settings,
        zip_bytes,
    ):
        """策略变更时只重新预检，不重传包。"""
        article = article_factory(
            staff_user, slug='replan-case', title='原标题', cover_bytes=jpeg_factory()
        )
        payload = export_zip(api_client, staff_header, article.id, zip_bytes)

        dry = stage(api_client, staff_header, payload, strategy='skip').json()['data']
        assert dry['items'][0]['action'] == 'skip'

        replanned = api_client.post(
            '/api/v1/admin/articles/import/plan/',
            {'staged_id': dry['staged_id'], 'strategy': 'update'},
            content_type='application/json',
            **staff_header,
        )
        assert replanned.status_code == 200, replanned.json()
        body = replanned.json()['data']
        assert body['items'][0]['action'] == 'update'
        assert body['staged_id'] == dry['staged_id']

    def test_replan_rejects_invalid_strategy(
        self, api_client, staff_header, package, archive_settings
    ):
        dry = stage(api_client, staff_header, package).json()['data']
        response = api_client.post(
            '/api/v1/admin/articles/import/plan/',
            {'staged_id': dry['staged_id'], 'strategy': 'boom'},
            content_type='application/json',
            **staff_header,
        )
        assert response.status_code == 400

    def test_replan_after_commit_conflicts(
        self, api_client, staff_header, package, archive_settings
    ):
        dry = stage(api_client, staff_header, package).json()['data']
        commit(api_client, staff_header, dry['staged_id'])
        response = api_client.post(
            '/api/v1/admin/articles/import/plan/',
            {'staged_id': dry['staged_id'], 'strategy': 'skip'},
            content_type='application/json',
            **staff_header,
        )
        assert response.status_code == 409

    def test_replan_requires_owner(self, api_client, staff_header, package, db, archive_settings):
        from django.contrib.auth import get_user_model
        from ninja_jwt.tokens import RefreshToken

        dry = stage(api_client, staff_header, package).json()['data']
        other = get_user_model().objects.create_user(
            username='replan-other', password='x', is_staff=True
        )
        header = {
            'HTTP_AUTHORIZATION': f'Bearer {RefreshToken.for_user(other).access_token}'
        }
        response = api_client.post(
            '/api/v1/admin/articles/import/plan/',
            {'staged_id': dry['staged_id'], 'strategy': 'skip'},
            content_type='application/json',
            **header,
        )
        assert response.status_code == 404


def test_generate_slug_is_importable():
    """确保测试辅助用的 slug 生成与实现一致（防止臆造）。"""
    assert generate_slug('境外游')
