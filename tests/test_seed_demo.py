"""`scripts/seed_demo.py` 产物可用性（TEST-11）。

`blog.sh seed-demo` 走的就是「生成归档包 → import stage/commit」这条真实链路，
这里把该链路抽成断言：生成器产物必须能被 stage 预检接受、被 commit 成功导入，
且正文 Markdown、内容寻址插图、封面/附件都完整落库。
"""
import importlib.util
import json
import os
import re
import zipfile
from pathlib import Path

import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile

from articles.archive import validate as archive_validate
from articles.archive.errors import PackageError
from articles.archive.format import ARTICLE_JSON_NAME, MANIFEST_NAME, README_NAME, SCHEMA_ARCHIVE
from articles.models import Article

pytestmark = pytest.mark.django_db

STAGE_URL = '/api/v1/admin/articles/import/stage/'
COMMIT_URL = '/api/v1/admin/articles/import/commit/'

SEED_DEMO_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'seed_demo.py'

INLINE_URL_RE = re.compile(r'/media/inline/[0-9a-f]{32}\.webp')


def _load_seed_demo():
    """按路径加载 `scripts/seed_demo.py`（scripts/ 不是包，不能直接 import）。"""
    spec = importlib.util.spec_from_file_location('seed_demo', SEED_DEMO_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def seed_demo():
    return _load_seed_demo()


def _read_article_jsons(path) -> list[dict]:
    """读出包内所有 article.json（按 slug 排序，顺序稳定）。"""
    payloads = []
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            if name.endswith(f'/{ARTICLE_JSON_NAME}'):
                payloads.append(json.loads(zf.read(name).decode('utf-8')))
    return sorted(payloads, key=lambda item: item['slug'])


@pytest.fixture(scope='module')
def seed_package(seed_demo, tmp_path_factory) -> Path:
    """生成一个 2 篇的演示包（count 调小以控制用例耗时，模块内复用）。"""
    out = tmp_path_factory.mktemp('seed_demo') / 'seed_demo.zip'
    count, size = seed_demo.build_package(str(out), count=2, author='admin')
    assert count == 2
    assert size == out.stat().st_size > 0
    return out


def _stage(api_client, staff_header, payload: bytes):
    response = api_client.post(
        STAGE_URL,
        {
            'file': SimpleUploadedFile('seed.zip', payload, content_type='application/zip'),
            'strategy': 'skip',
        },
        **staff_header,
    )
    assert response.status_code == 200, response.json()
    return response.json()['data']


def _commit(api_client, staff_header, staged_id):
    response = api_client.post(
        COMMIT_URL,
        {'staged_id': staged_id, 'strategy': 'skip'},
        content_type='application/json',
        **staff_header,
    )
    assert response.status_code == 200, response.json()
    return response.json()['data']


class TestPackageStructure:
    def test_contents_are_readable_and_self_describing(self, seed_package):
        with zipfile.ZipFile(seed_package) as zf:
            names = zf.namelist()
            assert MANIFEST_NAME in names
            assert README_NAME in names
            manifest = json.loads(zf.read(MANIFEST_NAME).decode('utf-8'))
        assert manifest['schema'] == SCHEMA_ARCHIVE
        assert len(manifest['articles']) == 2
        # 每篇都有封面 / 附件 / 内容寻址插图 / article.json
        for entry in manifest['articles']:
            prefix = entry['path'] + '/'
            members = [n for n in names if n.startswith(prefix)]
            assert any(n.endswith('/cover.jpg') for n in members)
            assert any(n.endswith('/attachment.pdf') for n in members)
            assert any(n.endswith('.webp') for n in members)
            assert f'{prefix}{ARTICLE_JSON_NAME}' in members

    def test_passes_package_validation_without_errors(self, seed_package):
        info = archive_validate.validate_package(seed_package)
        assert len(info.entries) == 2
        for entry in info.entries:
            assert entry.errors == [], entry.errors
        assert info.warnings == []

    def test_not_a_zip_is_rejected(self, tmp_path):
        bogus = tmp_path / 'bogus.zip'
        bogus.write_bytes(b'not a zip')
        with pytest.raises(PackageError):
            archive_validate.validate_package(bogus)


class TestImportPipeline:
    def test_stage_accepts_and_plans_all_creates(
        self, api_client, staff_header, archive_settings, seed_package
    ):
        dry = _stage(api_client, staff_header, seed_package.read_bytes())
        assert dry['dry_run'] is True
        assert dry['totals']['create'] == 2
        assert dry['totals']['failed'] == 0
        assert all(item['action'] == 'create' for item in dry['items'])

    def test_commit_imports_articles_with_content_and_media(
        self, api_client, staff_header, archive_settings, seed_package
    ):
        expected = _read_article_jsons(seed_package)

        dry = _stage(api_client, staff_header, seed_package.read_bytes())
        report = _commit(api_client, staff_header, dry['staged_id'])
        assert report['dry_run'] is False
        assert report['totals']['create'] == 2
        assert report['totals']['failed'] == 0

        assert Article.objects.count() == 2
        for payload in expected:
            article = Article.objects.get(slug=payload['slug'])
            assert article.title == payload['title']
            assert article.location == payload['location']
            assert article.is_published is True
            assert article.summary == payload['summary']
            # 正文（Markdown 原文）逐字保留
            assert article.content == payload['content']
            # 分类/标签随包内声明重建
            assert article.category is not None
            assert article.category.name == payload['category']['name']
            assert sorted(t.name for t in article.tags.all()) == sorted(
                tag['name'] for tag in payload['tags']
            )
            # 封面统一压成 WebP，且记录的是**当前落盘文件**的哈希
            assert article.cover_image.name.endswith('.webp')
            assert article.file_name.endswith('.pdf')

            # 正文引用的内容寻址插图必须真的落盘
            urls = INLINE_URL_RE.findall(article.content)
            assert urls, payload['content']
            for url in urls:
                stored = os.path.join(str(settings.MEDIA_ROOT), url[len('/media/'):])
                assert os.path.isfile(stored), stored

    def test_reimport_is_idempotent_and_skipped(
        self, api_client, staff_header, archive_settings, seed_package
    ):
        payload = seed_package.read_bytes()
        _commit(api_client, staff_header, _stage(api_client, staff_header, payload)['staged_id'])
        assert Article.objects.count() == 2

        dry = _stage(api_client, staff_header, payload)
        assert dry['totals']['skip'] == 2
        assert dry['totals']['create'] == 0

        report = _commit(api_client, staff_header, dry['staged_id'])
        assert report['totals']['skip'] == 2
        assert report['totals']['failed'] == 0
        assert Article.objects.count() == 2
