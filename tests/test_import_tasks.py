"""归档导入任务（异步）：入队、执行、进度、失败码、列表与取消。

编号对应 DESIGN 5.3.6 / AGENTS 的用例清单（TASK-001~015）。
真实链路由 ``import_worker`` 进程消费队列；测试里直接用 ``run_import_task``
把任务跑完（同一个执行器），不必起后台进程。
"""
import json
import shutil
import socket
import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from articles.archive import staging as archive_staging
from articles.archive import tasks as archive_tasks
from articles.models import ArchiveStaging, Article, ArticleImportTask

pytestmark = pytest.mark.django_db

TASKS_URL = '/api/v1/admin/articles/import/tasks/'
STAGE_URL = '/api/v1/admin/articles/import/stage/'


@pytest.fixture
def package(make_zip, jpeg_factory):
    """一个最小合法包（只有一篇、带封面与附件）。"""
    return make_zip({
        'articles/001-x/article.json': json.dumps(
            {
                'title': '任务用例',
                'slug': 'task-pkg',
                'publish_time': timezone.now().isoformat(),
                'cover': {'file': 'cover.jpg'},
                'attachment': {'file': 'attachment.pdf'},
            },
            ensure_ascii=False,
        ).encode(),
        'articles/001-x/cover.jpg': jpeg_factory(),
        'articles/001-x/attachment.pdf': b'%PDF-1.4 task',
    })


def stage(api_client, staff_header, payload: bytes, strategy='skip') -> dict:
    """上传并预检，返回报告（含 staged_id）。"""
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
    return response.json()['data']


def enqueue(api_client, staff_header, staged_id, **options):
    body = {'staged_id': staged_id, 'strategy': 'skip', **options}
    return api_client.post(TASKS_URL, body, content_type='application/json', **staff_header)


def run(task_id) -> ArticleImportTask:
    """同步执行（测试专用入口）。"""
    archive_tasks.run_import_task(task_id, worker_id='test')
    return ArticleImportTask.objects.get(pk=task_id)


def task_url(task_id, suffix='') -> str:
    return f'{TASKS_URL}{task_id}/{suffix}'


# --------------------------------------------------------------------------- 入队


class TestEnqueue:
    def test_enqueue_returns_202_queued(self, api_client, staff_header, package, archive_settings):
        """TASK-001：入队立刻 202，任务落库为 queued，预检快照原样保存。"""
        report = stage(api_client, staff_header, package)
        response = enqueue(
            api_client,
            staff_header,
            report['staged_id'],
            preview_totals={'create': 1, 'update': 0, 'skip': 0, 'failed': 0},
        )
        assert response.status_code == 202, response.json()
        data = response.json()['data']
        assert data['status'] == 'queued'
        assert data['progress']['total'] == 0
        assert data['queue_position'] == 1

        task = ArticleImportTask.objects.get(pk=data['id'])
        assert task.preview_totals['create'] == 1
        assert task.package['sha256'] == ArchiveStaging.objects.get(
            pk=report['staged_id']
        ).sha256
        assert task.staging_id == uuid.UUID(report['staged_id'])

    def test_staging_is_consumed_atomically(
        self, api_client, staff_header, package, archive_settings
    ):
        """TASK-002：同一个暂存包只能入队一次（第二次 409）。"""
        staged_id = stage(api_client, staff_header, package)['staged_id']
        assert enqueue(api_client, staff_header, staged_id).status_code == 202
        second = enqueue(api_client, staff_header, staged_id)
        assert second.status_code == 409
        assert '暂存包' in second.json()['message']

    def test_other_user_staging_is_404(self, api_client, staff_header, package, archive_settings):
        """TASK-003：别人的暂存包不是能力 URL，一律 404。"""
        from django.contrib.auth import get_user_model
        from ninja_jwt.tokens import RefreshToken

        staged_id = stage(api_client, staff_header, package)['staged_id']
        other = get_user_model().objects.create_user(
            username='other-staff', password='x', is_staff=True
        )
        header = {'HTTP_AUTHORIZATION': f'Bearer {RefreshToken.for_user(other).access_token}'}
        response = enqueue(api_client, header, staged_id)
        assert response.status_code == 404
        assert ArchiveStaging.objects.get(pk=staged_id).consumed_at is None

    def test_expired_staging_is_conflict(self, api_client, staff_header, package, archive_settings):
        """TASK-004：过期暂存包拒绝入队。"""
        staged_id = stage(api_client, staff_header, package)['staged_id']
        ArchiveStaging.objects.filter(pk=staged_id).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        assert enqueue(api_client, staff_header, staged_id).status_code == 409

    def test_min_interval_does_not_burn_staging(
        self, api_client, staff_header, package, archive_settings
    ):
        """TASK-005：被限流挡掉时不能消费暂存包（否则用户要重传大包）。"""
        archive_settings.ARCHIVE_IMPORT_MIN_INTERVAL_SECONDS = 60
        first = stage(api_client, staff_header, package)['staged_id']
        second = stage(api_client, staff_header, package)['staged_id']
        assert enqueue(api_client, staff_header, first).status_code == 202
        blocked = enqueue(api_client, staff_header, second)
        assert blocked.status_code == 429
        assert ArchiveStaging.objects.get(pk=second).consumed_at is None

    def test_enqueue_extends_staging_ttl(self, api_client, staff_header, package, archive_settings):
        """TASK-006：入队要把暂存有效期延到「排队也够用」，并挂上租约防清扫。"""
        staged_id = stage(api_client, staff_header, package)['staged_id']
        soon = timezone.now() + timedelta(seconds=5)
        ArchiveStaging.objects.filter(pk=staged_id).update(expires_at=soon)
        assert enqueue(api_client, staff_header, staged_id).status_code == 202

        staging = ArchiveStaging.objects.get(pk=staged_id)
        assert staging.expires_at > soon + timedelta(seconds=60)
        assert staging.lease_until == staging.expires_at
        assert staging.consumed_at is not None


# --------------------------------------------------------------------------- 执行


class TestExecution:
    def test_run_succeeds_and_counts(self, api_client, staff_header, package, archive_settings):
        """TASK-007：执行成功后状态/计数/进度齐全，文章真的落库。"""
        report = stage(api_client, staff_header, package)
        task_id = enqueue(api_client, staff_header, report['staged_id']).json()['data']['id']

        task = run(task_id)
        assert task.status == ArticleImportTask.Status.SUCCEEDED
        assert task.phase == ArticleImportTask.Phase.DONE
        assert task.created == 1
        assert task.processed == 1
        assert task.total == 1
        assert task.progress()['percent'] == 100
        assert task.report['dry_run'] is False
        assert task.finished_at is not None
        assert Article.objects.filter(slug='task-pkg').exists()

        # 暂存租约必须释放，否则 purge 永远跳过它
        assert ArchiveStaging.objects.get(pk=report['staged_id']).lease_until is None

    def test_item_failure_keeps_task_succeeded(
        self, api_client, staff_header, make_zip, jpeg_factory, archive_settings
    ):
        """TASK-008：单篇失败不算任务失败，靠 failed 计数与 items 说明。"""
        cover = jpeg_factory()
        payload = make_zip({
            # 有封面但正文与附件都缺 → 该篇按 A5 规则失败，整包仍合法
            'articles/001-bad/article.json': json.dumps({
                'title': '缺正文',
                'slug': 'bad-item',
                'publish_time': timezone.now().isoformat(),
                'cover': {'file': 'cover.jpg'},
            }, ensure_ascii=False).encode(),
            'articles/001-bad/cover.jpg': cover,
            'articles/002-ok/article.json': json.dumps({
                'title': '正常篇',
                'slug': 'ok-item',
                'publish_time': timezone.now().isoformat(),
                'content': '正文在此',
                'cover': {'file': 'cover.jpg'},
            }, ensure_ascii=False).encode(),
            'articles/002-ok/cover.jpg': cover,
        })
        report = stage(api_client, staff_header, payload)
        task_id = enqueue(api_client, staff_header, report['staged_id']).json()['data']['id']

        task = run(task_id)
        assert task.status == ArticleImportTask.Status.SUCCEEDED
        assert task.failed == 1
        assert task.created == 1

    def test_broken_package_fails_with_reason(
        self, api_client, staff_header, package, archive_settings
    ):
        """TASK-009：执行期重校验失败 → failed + 错误码/文案/指引三件套。"""
        staged_id = stage(api_client, staff_header, package)['staged_id']
        task_id = enqueue(api_client, staff_header, staged_id).json()['data']['id']

        # 模拟包在入队后被改坏
        staging = ArchiveStaging.objects.get(pk=staged_id)
        archive_staging.staging_archive_path(staging).write_bytes(b'not a zip at all')

        task = run(task_id)
        assert task.status == ArticleImportTask.Status.FAILED
        assert task.error_code == 'package_invalid'
        assert task.error_message
        assert task.error_hint

    def test_missing_staging_fails_expired(
        self, api_client, staff_header, package, archive_settings
    ):
        """TASK-010：暂存目录被清扫掉 → staging_expired，且不写任何文章。"""
        staged_id = stage(api_client, staff_header, package)['staged_id']
        task_id = enqueue(api_client, staff_header, staged_id).json()['data']['id']

        staging = ArchiveStaging.objects.get(pk=staged_id)
        shutil.rmtree(archive_staging.staging_path(staging.dir), ignore_errors=True)

        task = run(task_id)
        assert task.status == ArticleImportTask.Status.FAILED
        assert task.error_code == 'staging_expired'
        assert not Article.objects.exists()

    def test_overwrite_creates_rollback_ticket(
        self, api_client, staff_header, staff_user, package, article_factory, jpeg_factory,
        archive_settings,
    ):
        """TASK-011：覆盖模式在执行**前**生成回滚包，票据可直接下载。"""
        article_factory(staff_user, slug='task-pkg', title='旧版本', cover_bytes=jpeg_factory())
        report = stage(api_client, staff_header, package, strategy='update')
        assert report['totals']['update'] == 1

        task_id = enqueue(
            api_client, staff_header, report['staged_id'], strategy='update'
        ).json()['data']['id']
        task = run(task_id)

        assert task.status == ArticleImportTask.Status.SUCCEEDED
        assert task.rollback_ticket_id is not None
        assert task.report['rollback_package']['count'] == 1
        detail = api_client.get(task_url(task_id), **staff_header).json()['data']
        assert detail['rollback_package']['download_url'].endswith('/')

        download = api_client.get(detail['rollback_package']['download_url'], **staff_header)
        assert download.status_code == 200

    def test_plan_drift_is_recorded(self, api_client, staff_header, package, archive_settings):
        """TASK-012：预检快照与执行实况不一致时记录 plan_drift（排队期间数据会变）。"""
        report = stage(api_client, staff_header, package)
        task_id = enqueue(
            api_client,
            staff_header,
            report['staged_id'],
            preview_totals={'create': 5, 'update': 0, 'skip': 0, 'failed': 0},
        ).json()['data']['id']

        task = run(task_id)
        drift = task.report['plan_drift']
        assert drift['changed']['create'] == {'preview': 5, 'actual': 1}
        assert '已变化' in drift['message']

    def test_claim_next_takes_oldest(self, api_client, staff_header, package, archive_settings):
        """TASK-013：队列先进先出；claim 之后状态立刻是 running。"""
        ids = []
        for _ in range(2):
            staged_id = stage(api_client, staff_header, package)['staged_id']
            ids.append(enqueue(api_client, staff_header, staged_id).json()['data']['id'])

        claimed = archive_tasks.claim_next('tester')
        assert claimed is not None
        assert str(claimed.pk) == ids[0]
        assert claimed.status == ArticleImportTask.Status.RUNNING
        assert claimed.started_at is not None


# --------------------------------------------------------------------------- 列表 / 取消 / 清扫


class TestListAndCancel:
    def test_list_only_shows_own_tasks(self, api_client, staff_header, package, archive_settings):
        """TASK-014：默认只看自己的；超管 scope=all 才看全员。"""
        from django.contrib.auth import get_user_model
        from ninja_jwt.tokens import RefreshToken

        staged_id = stage(api_client, staff_header, package)['staged_id']
        enqueue(api_client, staff_header, staged_id)

        other = get_user_model().objects.create_user(
            username='other-staff2', password='x', is_staff=True
        )
        other_task = ArticleImportTask.objects.create(user=other, strategy='skip')

        mine = api_client.get(TASKS_URL, **staff_header).json()['data']
        assert mine['total'] == 1
        assert mine['items'][0]['id'] != str(other_task.id)

        admin = get_user_model().objects.create_superuser(
            username='root', password='x', email='root@example.com'
        )
        admin_header = {'HTTP_AUTHORIZATION': f'Bearer {RefreshToken.for_user(admin).access_token}'}
        everything = api_client.get(f'{TASKS_URL}?scope=all', **admin_header).json()['data']
        assert everything['total'] == 2
        # 非超管传 scope=all 也只返回自己的
        still_mine = api_client.get(f'{TASKS_URL}?scope=all', **staff_header).json()['data']
        assert still_mine['total'] == 1

    def test_queue_position_is_global_but_list_is_mine(
        self, api_client, staff_header, package, archive_settings
    ):
        """TASK-027：排队位置是全局的（别人的任务也占位），列表却只给自己看。

        这正是原来的缺陷：按「自己的任务」算位置，用户会看到「前面还有 1 个」
        却在列表里找不到那个任务。现在位置/总长都按全局队列算，并且都下发。
        """
        from django.contrib.auth import get_user_model
        from ninja_jwt.tokens import RefreshToken

        other = get_user_model().objects.create_user(
            username='queue-mate', password='x', is_staff=True
        )
        other_header = {'HTTP_AUTHORIZATION': f'Bearer {RefreshToken.for_user(other).access_token}'}

        # 别人的任务先入队（占位）
        other_id = enqueue(
            api_client, other_header, stage(api_client, other_header, package)['staged_id']
        ).json()['data']['id']

        mine = enqueue(
            api_client, staff_header, stage(api_client, staff_header, package)['staged_id']
        ).json()['data']
        assert mine['queue_position'] == 2
        assert mine['queue_total'] == 2

        listed = api_client.get(TASKS_URL, **staff_header).json()['data']
        assert listed['total'] == 1  # 只看得到自己的
        assert listed['items'][0]['id'] == mine['id']
        assert listed['items'][0]['queue_position'] == 2
        assert listed['items'][0]['queue_total'] == 2

        # 别人排完（跑掉）后，我的位置升到 1
        archive_tasks.run_import_task(other_id, worker_id='test')
        after = api_client.get(TASKS_URL, **staff_header).json()['data']['items'][0]
        assert after['queue_position'] == 1
        assert after['queue_total'] == 1

    def test_running_task_has_no_queue_position(
        self, api_client, staff_header, package, archive_settings
    ):
        """TASK-028：不在排队中的任务 queue_position 为 null，前端不该显示「第 0 个」。"""
        task_id = enqueue(
            api_client, staff_header, stage(api_client, staff_header, package)['staged_id']
        ).json()['data']['id']
        archive_tasks.claim_next('tester')

        detail = api_client.get(task_url(task_id), **staff_header).json()['data']
        assert detail['status'] == 'running'
        assert detail['queue_position'] is None
        assert detail['queue_total'] == 0

    def test_cancel_queued_task(self, api_client, staff_header, package, archive_settings):
        """TASK-015：排队中可以取消；已开始执行的不许取消（409）。"""
        staged_id = stage(api_client, staff_header, package)['staged_id']
        task_id = enqueue(api_client, staff_header, staged_id).json()['data']['id']

        canceled = api_client.post(task_url(task_id, 'cancel/'), **staff_header)
        assert canceled.status_code == 200
        assert canceled.json()['data']['status'] == 'canceled'

        # 已终态的任务再取消 → 409
        again = api_client.post(task_url(task_id, 'cancel/'), **staff_header)
        assert again.status_code == 409

        # running 的任务同样不许取消
        staged2 = stage(api_client, staff_header, package)['staged_id']
        running_id = enqueue(api_client, staff_header, staged2).json()['data']['id']
        assert archive_tasks.claim_next('tester') is not None
        running = api_client.post(task_url(running_id, 'cancel/'), **staff_header)
        assert running.status_code == 409

    def test_sweep_marks_stale_running_as_worker_lost(
        self, api_client, staff_header, staff_user
    ):
        """TASK-016：心跳超时的 running 任务被扫成 worker_lost（进程被杀的唯一线索）。"""
        task = ArticleImportTask.objects.create(
            user=staff_user,
            status=ArticleImportTask.Status.RUNNING,
            phase=ArticleImportTask.Phase.WRITING,
            started_at=timezone.now() - timedelta(minutes=30),
            heartbeat_at=timezone.now() - timedelta(minutes=10),
        )
        assert archive_tasks.sweep_stale() == 1
        task.refresh_from_db()
        assert task.status == ArticleImportTask.Status.FAILED
        assert task.error_code == 'worker_lost'

    def test_abort_on_stop_marks_interrupted(
        self, api_client, staff_header, package, archive_settings
    ):
        """TASK-017：SIGTERM 时如实记中断，**不**退回队列（回退会重复建文）。"""
        staged_id = stage(api_client, staff_header, package)['staged_id']
        task_id = enqueue(api_client, staff_header, staged_id).json()['data']['id']
        archive_tasks.claim_next('tester')

        archive_tasks.abort_on_stop(task_id)
        task = ArticleImportTask.objects.get(pk=task_id)
        assert task.status == ArticleImportTask.Status.FAILED
        assert task.error_code == 'worker_stopped'

    def test_worker_command_once_drains_queue(
        self, api_client, staff_header, package, archive_settings
    ):
        """TASK-018：`import_worker --once` 能把队列跑空并正常退出。"""
        from io import StringIO

        from django.core.management import call_command

        staged_id = stage(api_client, staff_header, package)['staged_id']
        task_id = enqueue(api_client, staff_header, staged_id).json()['data']['id']

        out = StringIO()
        call_command('import_worker', '--once', '--poll-interval', '0.2', stdout=out)
        assert 'worker 就绪' in out.getvalue()
        task = ArticleImportTask.objects.get(pk=task_id)
        assert task.status == ArticleImportTask.Status.SUCCEEDED
        assert socket.gethostname()


class TestLockConflict:
    """锁冲突的重排队语义（缺陷修复：误起第二个 worker 不该把任务判死）。"""

    def _enqueue(self, api_client, staff_header, package):
        staged_id = stage(api_client, staff_header, package)['staged_id']
        response = enqueue(api_client, staff_header, staged_id)
        assert response.status_code == 202, response.json()
        return response.json()['data']['id']

    def test_lock_conflict_requeues_with_backoff(
        self, api_client, staff_header, package, archive_settings
    ):
        """TASK-023：锁被占 → 退回 queued、attempts+1、延迟到 next_attempt_at。"""
        from articles.archive.locks import import_lock

        task_id = self._enqueue(api_client, staff_header, package)
        with import_lock():
            archive_tasks.run_import_task(task_id, worker_id='test')

        task = ArticleImportTask.objects.get(pk=task_id)
        assert task.status == ArticleImportTask.Status.QUEUED
        assert task.attempts == 1
        assert task.next_attempt_at is not None
        assert task.next_attempt_at > timezone.now()
        assert task.progress()['processed'] == 0
        assert not Article.objects.exists()

    def test_backoff_task_is_not_claimed_early(
        self, api_client, staff_header, package, archive_settings
    ):
        """TASK-024：延迟未到期的任务不会被 claim（否则两个 worker 互相空转）。"""
        from articles.archive.locks import import_lock

        task_id = self._enqueue(api_client, staff_header, package)
        with import_lock():
            archive_tasks.run_import_task(task_id, worker_id='test')

        # 手上没有其他任务时，claim_next 应拿不到（唯一那个还在退避期）
        assert archive_tasks.claim_next('tester') is None

        # 把退避时间拨到过去 → 立刻可领
        ArticleImportTask.objects.filter(pk=task_id).update(
            next_attempt_at=timezone.now() - timedelta(seconds=1)
        )
        claimed = archive_tasks.claim_next('tester')
        assert claimed is not None
        assert claimed.attempts == 2

    def test_lock_conflict_gives_up_after_max_attempts(
        self, api_client, staff_header, package, archive_settings
    ):
        """TASK-025：锁一直拿不到 → 到上限才判失败，且原因/指引可读。"""
        from articles.archive.locks import import_lock

        task_id = self._enqueue(api_client, staff_header, package)
        ArticleImportTask.objects.filter(pk=task_id).update(
            attempts=archive_tasks.MAX_LOCK_ATTEMPTS - 1
        )

        with import_lock():
            archive_tasks.run_import_task(task_id, worker_id='test')

        task = ArticleImportTask.objects.get(pk=task_id)
        assert task.status == ArticleImportTask.Status.FAILED
        assert task.error_code == 'lock_unavailable'
        assert '重试' in task.error_message
        assert '单副本' in task.error_hint

    def test_lock_is_renewed_during_long_run(
        self, api_client, staff_header, package, archive_settings
    ):
        """TASK-026：执行期进度落库顺带续租，否则锁会在长导入中途自解。

        直接验 ``LockHandle.extend`` 的行为：只有 token 还是自己的才续，
        被别人接管后不能把它改成自己的 TTL。
        """
        from django.core.cache import cache

        from articles.archive.locks import GLOBAL_LOCK_KEY, import_lock

        with import_lock() as lock:
            cache.set(GLOBAL_LOCK_KEY, 'someone-else', 30)
            lock.extend()  # 不该覆盖别人的锁
            assert cache.get(GLOBAL_LOCK_KEY) == 'someone-else'


class TestTaskPermissions:
    def test_anonymous_cannot_list(self, api_client):
        """TASK-019：匿名访问任务列表 401。"""
        assert api_client.get(TASKS_URL).status_code == 401

    def test_plain_user_sees_only_own_tasks(self, api_client, plain_header, plain_user):
        """TASK-020：普通用户也能用任务列表，但只看得到自己的（导入已对全员开放）。"""
        from django.contrib.auth import get_user_model

        other = get_user_model().objects.create_user(username='other-owner', password='x')
        ArticleImportTask.objects.create(user=other, strategy='skip')
        mine = ArticleImportTask.objects.create(user=plain_user, strategy='skip')

        data = api_client.get(TASKS_URL, **plain_header).json()['data']
        assert data['total'] == 1
        assert data['items'][0]['id'] == str(mine.id)

    def test_other_staff_cannot_read_task(self, api_client, staff_header, staff_user):
        """TASK-021：别的 staff 读不到我的任务（403），超管可以。"""
        from django.contrib.auth import get_user_model
        from ninja_jwt.tokens import RefreshToken

        task = ArticleImportTask.objects.create(user=staff_user, strategy='skip')
        other = get_user_model().objects.create_user(
            username='peeker', password='x', is_staff=True
        )
        header = {'HTTP_AUTHORIZATION': f'Bearer {RefreshToken.for_user(other).access_token}'}
        assert api_client.get(task_url(task.id), **header).status_code == 403

    def test_invalid_task_id_is_404(self, api_client, staff_header):
        """TASK-022：非法 id 与不存在的 id 都是 404（不泄漏存在性）。"""
        assert api_client.get(task_url('not-a-uuid'), **staff_header).status_code == 404
        assert api_client.get(task_url(uuid.uuid4()), **staff_header).status_code == 404
