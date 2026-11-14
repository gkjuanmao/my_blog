"""全员导入的写入边界：作者作用域、强制草稿、代传、排队上限、磁盘配额。

编号 IMP-（import policy）。前置：导入端点已对**任意登录用户**开放，
写域靠 planner 的 author 作用域保证，而不是「只给 staff」。
"""
import json

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from articles.archive import tasks as archive_tasks
from articles.models import ArchiveStaging, Article, ArticleImportTask

pytestmark = pytest.mark.django_db

STAGE_URL = '/api/v1/admin/articles/import/stage/'
TASKS_URL = '/api/v1/admin/articles/import/tasks/'


@pytest.fixture
def package(make_zip, jpeg_factory):
    """一篇带封面的最小包（slug 固定为 shared-slug，方便验证作用域）。"""
    return make_zip({
        'articles/001-x/article.json': json.dumps({
            'title': '作者的稿子',
            'slug': 'shared-slug',
            'publish_time': timezone.now().isoformat(),
            'content': '正文内容',
            'cover': {'file': 'cover.jpg'},
        }, ensure_ascii=False).encode(),
        'articles/001-x/cover.jpg': jpeg_factory(),
    })


@pytest.fixture
def plain_header(plain_user):
    from ninja_jwt.tokens import RefreshToken

    return {'HTTP_AUTHORIZATION': f'Bearer {RefreshToken.for_user(plain_user).access_token}'}


@pytest.fixture
def root_header(db):
    from ninja_jwt.tokens import RefreshToken

    root = get_user_model().objects.create_superuser(
        username='root-imp', password='x', email='r@e.com'
    )
    return {'HTTP_AUTHORIZATION': f'Bearer {RefreshToken.for_user(root).access_token}'}


def stage(api_client, header, payload, strategy='skip'):
    from django.core.files.uploadedfile import SimpleUploadedFile

    response = api_client.post(
        STAGE_URL,
        {
            'file': SimpleUploadedFile('pkg.zip', payload, content_type='application/zip'),
            'strategy': strategy,
        },
        **header,
    )
    assert response.status_code == 200, response.json()
    return response.json()['data']


def enqueue(api_client, header, staged_id, **options):
    return api_client.post(
        TASKS_URL,
        {'staged_id': staged_id, 'strategy': 'skip', **options},
        content_type='application/json',
        **header,
    )


class TestPlainAuthorImport:
    def test_imp_001_requires_draft(self, api_client, plain_header, package, archive_settings):
        """IMP-001 普通作者不带 as_draft 导入 → 403（外部内容不该直接上线）。"""
        staged_id = stage(api_client, plain_header, package)['staged_id']
        response = enqueue(api_client, plain_header, staged_id, auto_create_taxonomy=False)

        assert response.status_code == 403
        assert '草稿' in response.json()['message']

    def test_imp_002_requires_no_taxonomy_creation(
        self, api_client, plain_header, package, archive_settings
    ):
        """IMP-002 普通作者不能自动造分类/标签（否则分类树会被各人的命名塞满）。"""
        staged_id = stage(api_client, plain_header, package)['staged_id']
        response = enqueue(api_client, plain_header, staged_id, as_draft=True)

        assert response.status_code == 403
        assert '分类' in response.json()['message']

    def test_imp_003_cannot_assign_other_author(
        self, api_client, plain_header, plain_user, package, archive_settings
    ):
        """IMP-003 普通作者不能代传给别人。"""
        other = get_user_model().objects.create_user(username='someone-else', password='x')
        staged_id = stage(api_client, plain_header, package)['staged_id']
        response = enqueue(
            api_client,
            plain_header,
            staged_id,
            as_draft=True,
            auto_create_taxonomy=False,
            author_id=other.id,
        )

        assert response.status_code == 403

    def test_imp_004_plain_author_import_lands_as_draft(
        self, api_client, plain_header, plain_user, package, archive_settings
    ):
        """IMP-004 合法参数下，文章落在自己名下且是草稿。"""
        staged_id = stage(api_client, plain_header, package)['staged_id']
        response = enqueue(
            api_client, plain_header, staged_id, as_draft=True, auto_create_taxonomy=False
        )
        assert response.status_code == 202, response.json()

        task_id = response.json()['data']['id']
        archive_tasks.run_import_task(task_id, worker_id='test')

        article = Article.objects.get(slug='shared-slug')
        assert article.author_id == plain_user.id
        assert article.is_published is False  # 强制草稿


class TestAuthorScopedPlanner:
    def test_imp_005_other_authors_slug_is_not_touched(
        self,
        api_client,
        plain_header,
        article_factory,
        jpeg_factory,
        package,
        archive_settings,
    ):
        """IMP-005 同 slug 属于别人时，导入只能新建，不能覆盖。

        这是「开放全员导入」的硬前置：planner 全站匹配的话，A 导入会直接覆盖
        B 的同名文章（update 策略），而且 A 完全不知道。
        """
        owner = get_user_model().objects.create_user(username='slug-owner', password='x')
        mine = article_factory(
            owner, slug='shared-slug', title='别人的同名文章', cover_bytes=jpeg_factory()
        )

        staged_id = stage(api_client, plain_header, package, strategy='update')['staged_id']
        response = enqueue(
            api_client,
            plain_header,
            staged_id,
            strategy='update',
            as_draft=True,
            auto_create_taxonomy=False,
        )
        assert response.status_code == 202, response.json()
        task_id = response.json()['data']['id']
        archive_tasks.run_import_task(task_id, worker_id='test')

        mine.refresh_from_db()
        assert mine.title == '别人的同名文章'  # 没被覆盖
        task = ArticleImportTask.objects.get(pk=task_id)
        assert task.created == 1  # 新建了一篇（自己的）
        assert task.updated == 0
        # 两篇同名不同作者的文章并存
        assert Article.objects.filter(slug__startswith='shared-slug').count() == 2


class TestQueueAndQuota:
    def test_imp_006_queue_cap_per_user(
        self, api_client, plain_header, package, archive_settings
    ):
        """IMP-006 同一用户排队任务达上限 → 429（否则一人堵死全局队列）。"""
        for _ in range(2):
            staged_id = stage(api_client, plain_header, package)['staged_id']
            assert (
                enqueue(
                    api_client,
                    plain_header,
                    staged_id,
                    as_draft=True,
                    auto_create_taxonomy=False,
                ).status_code
                == 202
            )

        third = stage(api_client, plain_header, package)['staged_id']
        response = enqueue(
            api_client, plain_header, third, as_draft=True, auto_create_taxonomy=False
        )

        assert response.status_code == 429
        assert '排队' in response.json()['message']
        # 被挡掉时暂存包不能被消费（用户可以等一会儿重试）
        assert ArchiveStaging.objects.get(pk=third).consumed_at is None

    def test_imp_007_staging_quota(
        self, api_client, plain_header, package, archive_settings
    ):
        """IMP-007 单人暂存占盘超限 → 413（磁盘是所有用户共享的）。"""
        archive_settings.ARCHIVE_MAX_STAGING_BYTES_PER_USER = 10  # 比一个包还小
        from django.core.files.uploadedfile import SimpleUploadedFile

        response = api_client.post(
            STAGE_URL,
            {
                'file': SimpleUploadedFile('pkg.zip', package, content_type='application/zip'),
                'strategy': 'skip',
            },
            **plain_header,
        )

        assert response.status_code == 413
        assert 'MB' in response.json()['message']


class TestSuperuserProxyImport:
    def test_imp_008_superuser_can_import_for_another_author(
        self, api_client, root_header, package, archive_settings
    ):
        """IMP-008 超管代传：入队时指定 author_id，文章直接落在目标作者名下。"""
        target = get_user_model().objects.create_user(username='target-author', password='x')

        staged_id = stage(api_client, root_header, package)['staged_id']
        response = enqueue(api_client, root_header, staged_id, author_id=target.id)
        assert response.status_code == 202, response.json()

        task_id = response.json()['data']['id']
        task = ArticleImportTask.objects.get(pk=task_id)
        assert task.author_id == target.id

        archive_tasks.run_import_task(task_id, worker_id='test')

        article = Article.objects.get(slug='shared-slug')
        assert article.author_id == target.id

    def test_imp_009_proxy_target_must_be_active(
        self, api_client, root_header, package, archive_settings
    ):
        """IMP-009 代传给停用账号 → 400。"""
        disabled = get_user_model().objects.create_user(
            username='gone-author', password='x', is_active=False
        )
        staged_id = stage(api_client, root_header, package)['staged_id']
        response = enqueue(api_client, root_header, staged_id, author_id=disabled.id)

        assert response.status_code == 400
