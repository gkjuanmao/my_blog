"""归档导入任务的异步执行器（``import_worker`` 进程的业务核心）。

为什么要把执行逻辑从视图里搬出来：导入是分钟级长任务，同步执行会一直占着
HTTP 连接，前端 15s 超时先于服务端完成，用户看到「网络错误」但文章其实已写入。
这里把「执行」与「表达意图」彻底分离——视图只负责入队（毫秒级返回），
真正的重活由独立的 worker 进程按队列串行跑。

四条设计铁律（改动前先读）：

1. **计划不落库**：``build_plan`` 是对数据库的实时快照，排队任务的前置任务会
   改变快照结果。只存意图（staging + strategy + 开关），执行前现算。
2. **逐篇事务**：沿用 ``execute_plan`` 的语义，单篇失败不影响其它条目；
   worker 内**绝不**把整个导入包进一个事务（SQLite 上会让 web 端全部写超时）。
3. **进度落库要节流**：1000 篇逐篇 UPDATE 是 1000 次写事务，2s 落一次即可，
   顺带刷新 ``heartbeat_at`` 供 :func:`sweep_stale` 判定进程存活。
4. **回滚包先于执行**：覆盖模式下先打包 + 出票据并挂到任务上，这样即使后续
   中途失败，用户仍然拿得到「导入前」的还原点。
"""
import logging
import time
import uuid
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

from django.db import OperationalError
from django.db.models import F, Q
from django.utils import timezone

from articles.models import ArchiveStaging, ArchiveTicket, Article, ArticleImportTask

from . import errors as archive_errors
from . import export as archive_export
from . import importer as archive_importer
from . import planner as archive_planner
from . import staging as archive_staging
from . import validate as archive_validate
from .limits import Limits
from .limits import limits as archive_limits
from .locks import import_lock
from .report import package_info_dict

logger = logging.getLogger(__name__)

#: 进度写库的最小间隔（秒）
PROGRESS_FLUSH_SECONDS = 2.0
#: 超过这么久没心跳，说明执行进程已经死了（容器被杀/发版重启）
HEARTBEAT_STALE_SECONDS = 180
#: 错误信息落库前的截断长度（CharField 255）
MAX_MESSAGE_LEN = 255

#: 锁被别人占着时的重排队间隔（秒）。不能太短：真正的持锁者可能在跑十分钟，
#: 每 2s 撞一次锁等于让 worker 空转、并把重试次数白白烧光。
LOCK_RETRY_BACKOFF_SECONDS = 60
#: 锁冲突最多重排几次。60s × 16 ≈ 16 分钟，略长于 lock_ttl(900s)，
#: 这样「上一个执行者被 SIGKILL、锁靠 TTL 自解」的情况下仍等得到。
MAX_LOCK_ATTEMPTS = 16

#: 错误码 → （默认文案, 处理指引）。前端只展示，不参与判断。
ERROR_HINTS: dict[str, tuple[str, str]] = {
    'staging_expired': ('暂存包已过期，未执行任何导入', '重新上传压缩包后再导入'),
    'package_invalid': ('压缩包校验未通过', '确认 zip 未被手工改坏（或重新导出）后重传'),
    'limit_exceeded': ('压缩包超出归档上限', '拆分为多个小包，或调大 ARCHIVE_* 上限'),
    'disk_full': ('磁盘空间不足', '清理 private_archives 目录或扩容后重试'),
    'lock_unavailable': ('导入锁不可用（缓存/Redis 未就绪）', '检查 redis 容器状态，稍后重试'),
    'db_locked': ('数据库繁忙，写入等待超时', '稍后重试；频繁出现说明写入过于集中'),
    'worker_lost': (
        '任务被中断：执行进程已退出',
        '已写入的文章会保留，可用任务详情里的回滚包还原；确认后再重新导入',
    ),
    'worker_stopped': (
        '服务停止，任务被中断',
        '已写入的文章会保留；核对任务详情后再重新导入，必要时先用回滚包还原',
    ),
    'internal': (
        '导入过程中发生未预期错误',
        '查看 worker 日志：docker compose logs worker | grep import-task',
    ),
}


def _clip(text: str) -> str:
    return (text or '').replace('\n', ' ').strip()[:MAX_MESSAGE_LEN]


class _Progress:
    """把执行进度写回任务行（节流 + 心跳）。

    写库统一走 ``filter(pk=...).update()``：既不碰模型实例的其它字段，
    也不会有「读到旧快照再整行写回」的丢更新问题（与文章 views 计数的教训同源）。
    """

    def __init__(
        self,
        task_id,
        *,
        interval: float = PROGRESS_FLUSH_SECONDS,
        on_tick: Callable[[], None] | None = None,
    ) -> None:
        self.task_id = task_id
        self.interval = interval
        # 顺带做的事（目前是给导入锁续租）：导入可能跑超过 lock_ttl，
        # 不续租的话锁会半路自解，第二个执行者就能同时写库
        self.on_tick = on_tick
        self.phase: str = ArticleImportTask.Phase.WAITING
        self.label = ''
        self.total = 0
        self.processed = 0
        self.created = 0
        self.updated = 0
        self.skipped = 0
        self.failed = 0
        self._last = 0.0
        self._frozen = False

    def snapshot(self) -> dict:
        return {
            'phase': self.phase,
            'phase_label': _clip(self.label) if self.label else '',
            'total': self.total,
            'processed': self.processed,
            'created': self.created,
            'updated': self.updated,
            'skipped': self.skipped,
            'failed': self.failed,
            'heartbeat_at': timezone.now(),
        }

    def write(self) -> None:
        if self._frozen:
            return
        ArticleImportTask.objects.filter(pk=self.task_id).update(**self.snapshot())
        self._last = time.monotonic()
        if self.on_tick is not None:
            self.on_tick()

    def freeze(self) -> None:
        """进入终态后停止再写进度，避免把失败的 phase_label 覆盖回去。"""
        self._frozen = True

    def start_phase(self, phase: str, label: str = '') -> None:
        self.phase = phase
        self.label = label
        self.write()

    def item_done(self, action: str) -> None:
        """``execute_plan`` 的单篇回调。"""
        self.processed += 1
        if action == 'create':
            self.created += 1
        elif action == 'update':
            self.updated += 1
        elif action == 'skip':
            self.skipped += 1
        elif action == 'failed':
            self.failed += 1
        self.label = (
            f'写入文章 {self.processed}/{self.total}'
            if self.total
            else f'已写入 {self.processed} 篇'
        )
        if time.monotonic() - self._last >= self.interval:
            self.write()


def claim_next(worker_id: str) -> ArticleImportTask | None:
    """取队首任务并原子置为 running（``update() == 1`` 才算抢到）。

    跳过 ``next_attempt_at`` 还没到的任务：那是锁冲突后延迟重排的，提前抢会
    让两个执行者在锁上空转（每 2s 抢一次、失败一次）。
    """
    now = timezone.now()
    while True:
        candidate = (
            ArticleImportTask.objects.filter(status=ArticleImportTask.Status.QUEUED)
            .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
            .order_by('created_at')
            .first()
        )
        if candidate is None:
            return None
        claimed = ArticleImportTask.objects.filter(
            pk=candidate.pk, status=ArticleImportTask.Status.QUEUED
        ).update(
            status=ArticleImportTask.Status.RUNNING,
            phase=ArticleImportTask.Phase.VALIDATING,
            phase_label='正在校验压缩包…',
            started_at=now,
            heartbeat_at=now,
            attempts=F('attempts') + 1,
            next_attempt_at=None,
            worker_id=worker_id[:64],
        )
        if claimed == 1:
            candidate.refresh_from_db()
            return candidate
        # 极端情况下被另一个执行者抢走：重来一轮（正常情况下永远走不到）


def _requeue_after_lock_conflict(task: ArticleImportTask) -> ArticleImportTask:
    """锁被别的执行者占着：**退回去排队**，而不是把任务判死。

    为什么不再直接失败：单 worker 下永远不该冲突，会冲突只有两种原因——
    有人手工跑了第二个 ``import_worker``（排障时很常见），或误用了
    ``--scale worker=2``。这两种都属于「等一会儿就能好」，判死等于平白丢掉一次
    导入（暂存包已消费，用户得重传）。冲突始终发生在**任何写入之前**（锁包住整个
    执行段），所以重排是安全的、不会重复建文。

    重排用 ``next_attempt_at`` 延迟，避免两个 worker 每 2s 互撞空转；
    超过 :data:`MAX_LOCK_ATTEMPTS` 次仍然冲突才判失败（意味着锁真的卡住了）。
    """
    if task.attempts >= MAX_LOCK_ATTEMPTS:
        return fail_task(
            task,
            'lock_unavailable',
            message=f'等待导入锁超过 {MAX_LOCK_ATTEMPTS} 次重试（约 {MAX_LOCK_ATTEMPTS} 分钟）',
            hint='检查是否误起了第二个 worker（必须单副本），或稍后重新上传导入',
        )
    now = timezone.now()
    ArticleImportTask.objects.filter(
        pk=task.pk, status=ArticleImportTask.Status.RUNNING
    ).update(
        status=ArticleImportTask.Status.QUEUED,
        phase=ArticleImportTask.Phase.WAITING,
        phase_label=f'等待前一个导入结束（第 {task.attempts} 次重试）',
        started_at=None,
        heartbeat_at=None,
        worker_id='',
        next_attempt_at=now + timedelta(seconds=LOCK_RETRY_BACKOFF_SECONDS),
    )
    logger.warning(
        'import-task %s 导入锁被占用，%ds 后重试（第 %d/%d 次）',
        task.pk,
        LOCK_RETRY_BACKOFF_SECONDS,
        task.attempts,
        MAX_LOCK_ATTEMPTS,
    )
    task.refresh_from_db()
    return task


def fail_task(
    task: ArticleImportTask,
    code: str,
    message: str | None = None,
    hint: str | None = None,
) -> ArticleImportTask:
    """把任务置为失败终态（幂等：已经是终态就不覆盖）。"""
    default_message, default_hint = ERROR_HINTS.get(code, ERROR_HINTS['internal'])
    now = timezone.now()
    ArticleImportTask.objects.filter(
        pk=task.pk, status__in=ArticleImportTask.ACTIVE_STATUSES
    ).update(
        status=ArticleImportTask.Status.FAILED,
        phase=ArticleImportTask.Phase.DONE,
        phase_label='失败',
        error_code=code if code in ERROR_HINTS else 'internal',
        error_message=_clip(message or default_message),
        error_hint=_clip(hint or default_hint),
        finished_at=now,
        heartbeat_at=now,
    )
    task.refresh_from_db()
    return task


def sweep_stale(*, now=None) -> int:
    """回收「进程被杀但任务停在 running」的僵尸任务。

    只扫心跳陈旧的 running，不做自动重跑——半途重跑会重复建文章
    （``create_new`` 虽有 identical 兜底，但 ``update`` 会二次覆盖）。
    """
    moment = now or timezone.now()
    cutoff = moment - timedelta(seconds=HEARTBEAT_STALE_SECONDS)
    stale = ArticleImportTask.objects.filter(status=ArticleImportTask.Status.RUNNING).filter(
        Q(heartbeat_at__isnull=True) | Q(heartbeat_at__lt=cutoff)
    )
    count = 0
    for task in stale:
        logger.warning('import-task %s 心跳超时，标记为 worker_lost', task.pk)
        fail_task(task, 'worker_lost')
        count += 1
    return count


def abort_on_stop(task_id) -> None:
    """worker 收到 SIGTERM 且手上有任务在跑时的收尾。

    **不退回队列**：进程收到信号后并不会立刻死，它还会继续写库；此时把任务
    改回 queued，一旦容器在 grace period 后被杀，新 worker 会重跑同一份暂存包
    → 重复建文/重复覆盖。因此这里一律如实记 ``worker_stopped``，让用户在
    任务详情里看到真实进度再决定是否重导。
    """
    task = ArticleImportTask.objects.filter(pk=task_id).first()
    if task is None or task.status != ArticleImportTask.Status.RUNNING:
        return
    fail_task(task, 'worker_stopped')


def _plan_drift(preview: dict, current: dict) -> dict | None:
    """预检快照与执行时实况的差异（排队期间前置任务会改变结果）。"""
    keys = ('create', 'update', 'skip', 'failed')
    if not preview or not any(key in preview for key in keys):
        return None
    changed = {
        key: {'preview': preview.get(key, 0), 'actual': current.get(key, 0)}
        for key in keys
        if preview.get(key, 0) != current.get(key, 0)
    }
    if not changed:
        return None
    return {
        'changed': changed,
        'message': '排队期间数据已变化，实际执行与提交时的预检不同',
    }


def _build_rollback(
    task: ArticleImportTask, plan: archive_planner.Plan, lim: Limits
) -> dict | None:
    """覆盖模式下打包「导入前」的文章并出票据，立即挂到任务上。"""
    affected = list(
        Article.objects.filter(pk__in=plan.touched_ids)
        .select_related('author', 'category')
        .prefetch_related('tags')
    )
    if not affected:
        return None
    archive_staging.ensure_subdirs()
    out_path = (
        archive_staging.archive_root()
        / archive_staging.ROLLBACKS_DIR
        / f'{uuid.uuid4().hex}.zip'
    )
    archive_export.build_rollback_archive(affected, out_path, lim=lim)
    ticket = archive_staging.create_ticket(
        user=task.user,
        kind=ArchiveTicket.Kind.ROLLBACK,
        path=out_path,
        filename=f'rollback-{archive_export.export_filename()}',
        size=out_path.stat().st_size,
    )
    ArticleImportTask.objects.filter(pk=task.pk).update(rollback_ticket=ticket)
    task.rollback_ticket = ticket
    return {
        'count': len(affected),
        'ticket': str(ticket.id),
        'download_url': f'/api/v1/admin/archives/{ticket.id}/',
        'expires_at': ticket.expires_at.isoformat(),
    }


def _error_code(exc: BaseException) -> tuple[str, str | None]:
    """异常 → （错误码, 原始信息）。原始信息仅在内部错误时透出首行。"""
    if isinstance(exc, archive_errors.LockUnavailable):
        return 'lock_unavailable', None
    if isinstance(exc, archive_errors.ArchiveError):
        code = exc.code or 'package_invalid'
        if code in ('conflict', 'rate_limited'):
            # 单 worker 下不该出现；真出现说明有第二个执行者，按锁不可用处理
            return 'lock_unavailable', exc.message
        return (code if code in ERROR_HINTS else 'package_invalid'), exc.message
    if isinstance(exc, OperationalError):
        text = str(exc).lower()
        if 'locked' in text or 'busy' in text:
            return 'db_locked', None
        return 'internal', str(exc).splitlines()[0] if str(exc) else None
    if isinstance(exc, OSError):
        if getattr(exc, 'errno', None) == 28:  # ENOSPC
            return 'disk_full', None
        return 'internal', (str(exc).splitlines()[0] if str(exc) else None)
    return 'internal', (str(exc).splitlines()[0] if str(exc) else None)


def _finish_success(task: ArticleImportTask, progress: _Progress, report: dict) -> None:
    now = timezone.now()
    progress.freeze()
    ArticleImportTask.objects.filter(pk=task.pk).update(
        status=ArticleImportTask.Status.SUCCEEDED,
        phase=ArticleImportTask.Phase.DONE,
        phase_label='已完成',
        total=progress.total,
        processed=progress.processed,
        created=progress.created,
        updated=progress.updated,
        skipped=progress.skipped,
        failed=progress.failed,
        report=report,
        finished_at=now,
        heartbeat_at=now,
        error_code='',
        error_message='',
        error_hint='',
    )


def run_import_task(task_id, *, worker_id: str = '') -> ArticleImportTask | None:
    """执行一个导入任务（worker 循环与测试共用入口）。

    幂等前提：任务处于 running（或 queued，本函数会自动补 claim）。
    任何异常都不会向外抛——失败要落库成任务状态，而不是让 worker 崩掉。

    Args:
        task_id: 任务主键。
        worker_id: 执行进程标识，仅用于诊断。

    Returns:
        执行后的任务实例；任务不存在时返回 ``None``。
    """
    task = ArticleImportTask.objects.filter(pk=task_id).first()
    if task is None:
        logger.warning('import-task 不存在: %s', task_id)
        return None

    if task.status == ArticleImportTask.Status.QUEUED:
        # 直接调用（测试/手工重跑）时补一次 claim，与 claim_next 语义一致
        ArticleImportTask.objects.filter(
            pk=task.pk, status=ArticleImportTask.Status.QUEUED
        ).update(
            status=ArticleImportTask.Status.RUNNING,
            started_at=timezone.now(),
            heartbeat_at=timezone.now(),
            attempts=F('attempts') + 1,
            next_attempt_at=None,
            worker_id=worker_id[:64],
        )
        task.refresh_from_db()

    if task.status != ArticleImportTask.Status.RUNNING:
        logger.info('import-task %s 状态为 %s，跳过执行', task.pk, task.status)
        return task

    lim = archive_limits()
    # 进度上报顺带续租导入锁（拿到锁之后再把 extend 挂上去）
    progress = _Progress(task.pk)
    staging: ArchiveStaging | None = task.staging

    try:
        if staging is None:
            return fail_task(task, 'staging_expired')
        if staging.expires_at <= timezone.now():
            return fail_task(task, 'staging_expired')
        package_path = archive_staging.staging_archive_path(staging)
        if not Path(package_path).exists():
            return fail_task(task, 'staging_expired')

        with import_lock(lim) as lock:
            # 大包导入可能跑超过 lock_ttl，靠每次进度落库顺带续租，防止锁半路自解
            progress.on_tick = lock.extend
            progress.start_phase(ArticleImportTask.Phase.VALIDATING, '正在校验压缩包…')
            info = archive_validate.validate_package(package_path, limits_override=lim)
            plan = archive_planner.build_plan(
                info.entries, strategy=task.strategy, user=task.user, lim=lim
            )
            package = package_info_dict(info)
            progress.total = len(plan.items)
            progress.write()

            drift = _plan_drift(task.preview_totals, plan.totals())

            rollback: dict | None = None
            if plan.has_overwrite:
                progress.start_phase(
                    ArticleImportTask.Phase.SNAPSHOTTING,
                    f'正在生成回滚包（{len(plan.touched_ids)} 篇）…',
                )
                rollback = _build_rollback(task, plan, lim)

            progress.start_phase(
                ArticleImportTask.Phase.WRITING, f'写入文章 0/{progress.total}'
            )
            options = archive_importer.ImportOptions(
                strategy=task.strategy,
                auto_create_taxonomy=task.auto_create_taxonomy,
                as_draft=task.as_draft,
                user=task.user,
            )
            report = archive_importer.execute_plan(
                plan,
                options=options,
                package=package,
                package_path=package_path,
                on_item=lambda _index, item: progress.item_done(item['action']),
            )
            data: dict[str, Any] = report.to_dict(
                dry_run=False, plan=plan, package=package
            )
            if drift:
                data['plan_drift'] = drift
            data['rollback_package'] = rollback
            data['task_id'] = str(task.pk)
            _finish_success(task, progress, data)
            logger.info(
                'import-task %s 完成：新建 %d / 覆盖 %d / 跳过 %d / 失败 %d',
                task.pk,
                progress.created,
                progress.updated,
                progress.skipped,
                progress.failed,
            )
    except archive_errors.ConflictError:
        # 锁被别的执行者占着：退回队列等下一轮（见 _requeue_after_lock_conflict）
        progress.freeze()
        _requeue_after_lock_conflict(task)
    except Exception as exc:  # noqa: BLE001 - worker 绝不能被单任务打挂
        code, detail = _error_code(exc)
        if code == 'internal':
            logger.exception('import-task %s 执行失败', task.pk)
        else:
            logger.warning('import-task %s 失败（%s）：%s', task.pk, code, exc)
        progress.freeze()
        default_message, _ = ERROR_HINTS.get(code, ERROR_HINTS['internal'])
        fail_task(
            task,
            code,
            message=f'{default_message}：{detail}' if detail and code != 'internal' else None,
        )
    finally:
        # 释放暂存包租约，否则 purge 永远跳过它（磁盘只涨不降）。
        # ⚠️ 只有终态才释放：锁冲突会被**退回队列**（任务还活着），此时清租约等于
        # 让 purge 有机会在两次尝试之间把暂存包扫掉，下一轮就变成 staging_expired。
        task.refresh_from_db()
        if staging is not None and task.is_terminal:
            ArchiveStaging.objects.filter(pk=staging.pk).update(lease_until=None)
        progress.write()

    task.refresh_from_db()
    return task
