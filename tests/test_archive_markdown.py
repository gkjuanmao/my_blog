"""归档 v2：正文与内联图的导出/导入往返、幂等、缺省附件与兼容性。"""
import hashlib
import json
import os
import zipfile

import pytest
from django.conf import settings

from articles.archive import export as archive_export
from articles.archive import importer as archive_importer
from articles.archive import planner as archive_planner
from articles.archive import validate as archive_validate
from articles.images import inline_url, process_inline_image, store_inline_image
from articles.models import Article


def _inline_path(rel: str) -> str:
    return os.path.join(str(settings.MEDIA_ROOT), rel)


def _run_import(path, *, strategy: str, user, settings_override=None):
    info = archive_validate.validate_package(path)
    plan = archive_planner.build_plan(info.entries, strategy=strategy, user=user)
    options = archive_importer.ImportOptions(strategy=strategy, user=user)
    report = archive_importer.execute_plan(
        plan, options=options, package={}, package_path=path
    )
    return info, plan, report


def _article_json(*, slug='demo', title='演示', content='', cover=None, images=None,
                  attachment=None, schema='myblog.article/v2') -> dict:
    payload = {
        'schema': schema,
        'title': title,
        'slug': slug,
        'publish_time': '2026-08-09T14:00:00+08:00',
        'is_published': True,
        'cover': cover,
        'attachment': attachment,
        'images': images or [],
        'import': {'action': 'auto'},
    }
    if content:
        payload['content'] = content
    return payload


def _cover_meta(jpeg: bytes) -> dict:
    return {
        'file': 'cover.jpg',
        'original_name': 'c.jpg',
        'sha256': hashlib.sha256(jpeg).hexdigest(),
        'size': len(jpeg),
    }


@pytest.mark.django_db
class TestRoundTrip:
    def _article_with_image(self, user, article_factory, jpeg_factory):
        processed = process_inline_image(jpeg_factory(size=(40, 30)), 'jpg')
        rel = store_inline_image(processed.data)
        url = inline_url(processed.data)
        content = f'# 带图正文\n\n![插图]({url})\n\n正文结束。'
        article = article_factory(
            user,
            slug='round-trip',
            cover_bytes=jpeg_factory(size=(60, 40)),
            pdf_bytes=b'%PDF-1.4 body',
        )
        article.content = content
        article.save(update_fields=['content'])
        return article, rel, content

    def test_export_import_restores_content_and_images(
        self, tmp_path, user, article_factory, jpeg_factory
    ):
        article, rel, content = self._article_with_image(user, article_factory, jpeg_factory)
        out = tmp_path / 'pkg.zip'
        archive_export.build_archive([article], out)

        # 模拟"换机"：文章与插图文件都不在了
        slug = article.slug
        article.delete()
        os.remove(_inline_path(rel))
        assert not os.path.isfile(_inline_path(rel))

        _, plan, report = _run_import(out, strategy='skip', user=user)

        assert [i['action'] for i in report.items] == ['create']
        restored = Article.objects.get(slug=slug)
        assert restored.content == content
        assert os.path.isfile(_inline_path(rel))

    def test_reexport_is_stable(self, tmp_path, user, article_factory, jpeg_factory):
        """导出 → 导入 → 再导出：正文与插图集合不变（不每轮重写）。"""
        article, _rel, content = self._article_with_image(user, article_factory, jpeg_factory)
        first = tmp_path / 'first.zip'
        archive_export.build_archive([article], first)

        article.delete()
        _run_import(first, strategy='skip', user=user)
        restored = Article.objects.get(slug='round-trip')

        second = tmp_path / 'second.zip'
        archive_export.build_archive([restored], second)

        def payload(path):
            with zipfile.ZipFile(path) as zf:
                name = next(n for n in zf.namelist() if n.endswith('article.json'))
                return json.loads(zf.read(name)), sorted(
                    n for n in zf.namelist() if '/images/' in n
                )

        payload_a, images_a = payload(first)
        payload_b, images_b = payload(second)
        assert payload_a['content'] == payload_b['content'] == content
        assert images_a == images_b and len(images_a) == 1

    def test_update_import_is_idempotent(self, tmp_path, user, article_factory, jpeg_factory):
        article, rel, _content = self._article_with_image(user, article_factory, jpeg_factory)
        out = tmp_path / 'pkg.zip'
        archive_export.build_archive([article], out)

        _run_import(out, strategy='update', user=user)
        files_after_first = os.listdir(os.path.dirname(_inline_path(rel)))

        _, _, report = _run_import(out, strategy='update', user=user)

        assert all(i['action'] == 'update' for i in report.items)
        assert os.listdir(os.path.dirname(_inline_path(rel))) == files_after_first


@pytest.mark.django_db
class TestOptionalAttachment:
    def test_export_and_import_without_attachment(
        self, tmp_path, user, article_factory, jpeg_factory
    ):
        article = article_factory(user, slug='text-only', cover_bytes=jpeg_factory())
        article.file = ''
        article.file_name = ''
        article.file_sha256 = ''
        article.content = '只有正文，没有附件。'
        article.save(update_fields=['file', 'file_name', 'file_sha256', 'content'])

        out = tmp_path / 'pkg.zip'
        archive_export.build_archive([article], out)
        with zipfile.ZipFile(out) as zf:
            name = next(n for n in zf.namelist() if n.endswith('article.json'))
            assert json.loads(zf.read(name))['attachment'] is None

        article.delete()
        _, plan, report = _run_import(out, strategy='skip', user=user)

        assert plan.items[0].action == 'create'
        restored = Article.objects.get(slug='text-only')
        assert restored.content == '只有正文，没有附件。'
        assert not restored.file


@pytest.mark.django_db
class TestCompatibility:
    def test_v1_package_without_content(self, tmp_path, user, make_zip, jpeg_factory):
        """旧包（v1，无 content/images，附件必填）仍可导入，并给出 schema 告警。"""
        jpeg = jpeg_factory()
        pdf = b'%PDF-1.4 legacy'
        attachment = {
            'file': 'attachment.pdf',
            'original_name': 'legacy.pdf',
            'sha256': hashlib.sha256(pdf).hexdigest(),
            'size': len(pdf),
        }
        package = make_zip({
            'articles/001-legacy/article.json': json.dumps(
                _article_json(
                    slug='legacy',
                    schema='myblog.article/v1',
                    cover=_cover_meta(jpeg),
                    attachment=attachment,
                )
            ).encode(),
            'articles/001-legacy/cover.jpg': jpeg,
            'articles/001-legacy/attachment.pdf': pdf,
        })
        path = tmp_path / 'v1.zip'
        path.write_bytes(package)

        info, plan, report = _run_import(path, strategy='skip', user=user)

        assert plan.items[0].action == 'create'
        assert any('旧版格式' in w for w in info.entries[0].all_warnings())
        restored = Article.objects.get(slug='legacy')
        assert restored.content == ''
        assert restored.file

    def test_v2_package_accepted(self, tmp_path, user, make_zip, jpeg_factory):
        jpeg = jpeg_factory()
        package = make_zip({
            'articles/001-new/article.json': json.dumps(
                _article_json(slug='new', content='正文', cover=_cover_meta(jpeg))
            ).encode(),
            'articles/001-new/cover.jpg': jpeg,
        })
        path = tmp_path / 'v2.zip'
        path.write_bytes(package)

        info, plan, _report = _run_import(path, strategy='skip', user=user)

        assert not info.entries[0].warnings
        assert Article.objects.get(slug='new').content == '正文'

    def test_missing_referenced_image_warns(self, tmp_path, user, make_zip, jpeg_factory):
        jpeg = jpeg_factory()
        package = make_zip({
            'articles/001-warn/article.json': json.dumps(
                _article_json(
                    slug='warn',
                    content='![x](/media/inline/absent.webp) 正文',
                    cover=_cover_meta(jpeg),
                )
            ).encode(),
            'articles/001-warn/cover.jpg': jpeg,
        })
        path = tmp_path / 'warn.zip'
        path.write_bytes(package)

        info, _plan, _report = _run_import(path, strategy='skip', user=user)

        assert any('未随包提供' in w for w in info.entries[0].all_warnings())


@pytest.mark.django_db
class TestIdempotencyKey:
    def test_changed_content_is_not_identical(self, tmp_path, user, article_factory,
                                              jpeg_factory):
        """正文改过的包，create_new 不应被判 identical 而跳过。"""
        article = article_factory(user, slug='kernel', cover_bytes=jpeg_factory())
        article.content = '原始正文'
        article.save(update_fields=['content'])

        out = tmp_path / 'pkg.zip'
        archive_export.build_archive([article], out)

        # 改写包内正文，使内容与原文章不同
        patched = tmp_path / 'patched.zip'
        with zipfile.ZipFile(out) as src, zipfile.ZipFile(patched, 'w') as dst:
            for item in src.infolist():
                data = src.read(item.filename)
                if item.filename.endswith('article.json'):
                    payload = json.loads(data)
                    payload['content'] = '改过的正文'
                    data = json.dumps(payload, ensure_ascii=False, indent=2).encode()
                dst.writestr(item, data)

        _, plan, report = _run_import(patched, strategy='create_new', user=user)

        assert plan.items[0].action == 'create'
        assert report.items[0]['action'] == 'create'
