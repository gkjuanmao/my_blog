"""归档导入任务的执行进程（``python manage.py import_worker``）。

部署形态：docker-compose 里的独立 service，与 app **同镜像、不同 command**，
共享 db_data / media / private_archives 三个卷。为什么不做成「请求线程」或
「容器内后台进程」：见 DESIGN 5.3.6 —— 前者随 gunicorn 重启丢任务，后者
收不到 docker 的 SIGTERM，会硬杀在写库中间。

⚠️ **必须单副本**：串行执行、回滚包顺序、导入锁都建立在「全局只有一个执行者」
之上。``--scale worker=2`` 会让两个导入同时写 SQLite 且互相覆盖。
"""
import logging
import os
import signal
import socket
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from articles.archive import tasks as archive_tasks

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL = 2.0
#: 僵尸任务扫描间隔（秒）
SWEEP_INTERVAL_SECONDS = 60


class Command(BaseCommand):
    help = '消费归档导入任务队列（单进程串行执行，必须单副本运行）'

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            '--once',
            action='store_true',
            help='把当前队列跑空后退出（调试/测试用）',
        )
        parser.add_argument(
            '--poll-interval',
            type=float,
            default=DEFAULT_POLL_INTERVAL,
            help=f'空闲轮询间隔秒数（默认 {DEFAULT_POLL_INTERVAL}）',
        )

    def handle(self, *args, **options) -> None:
        once: bool = bool(options['once'])
        interval: float = max(0.2, float(options['poll_interval']))
        # 容器名 + pid 足以在日志里区分「哪次部署的哪个进程」
        worker_id = f'{os.environ.get("HOSTNAME") or socket.gethostname()}:{os.getpid()}'

        stopping = False
        # 手上的任务 id：SIGTERM 时要能立刻把中断状态落库（见 abort_on_stop 注释）
        current: dict[str, object] = {'task_id': None}

        def _stop(signum, _frame) -> None:
            nonlocal stopping
            stopping = True
            logger.warning('收到信号 %s，当前任务收尾后退出', signum)
            task_id = current.get('task_id')
            if task_id is not None:
                try:
                    archive_tasks.abort_on_stop(task_id)
                except Exception:  # noqa: BLE001
                    logger.exception('中断任务状态写入失败')

        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)

        stale = archive_tasks.sweep_stale()
        if stale:
            logger.warning('启动清扫：%d 个僵尸任务已标记为 worker_lost', stale)

        self.stdout.write(
            self.style.SUCCESS(f'worker 就绪（{worker_id}），轮询间隔 {interval}s')
        )

        last_sweep = time.monotonic()
        while not stopping:
            # 长驻进程必须每轮回收旧连接：SQLite 空闲后连接可能已失效
            close_old_connections()
            task = None
            try:
                task = archive_tasks.claim_next(worker_id)
                if task is not None:
                    current['task_id'] = task.pk
                    logger.info('开始执行 import-task %s', task.pk)
                    archive_tasks.run_import_task(task.pk, worker_id=worker_id)
                    current['task_id'] = None
                    if once:
                        break
                    continue
            except Exception:  # noqa: BLE001 - 任何异常都不能让 worker 退出
                logger.exception('执行 import-task 失败，继续轮询')
                current['task_id'] = None

            if once:
                break

            if time.monotonic() - last_sweep >= SWEEP_INTERVAL_SECONDS:
                try:
                    archive_tasks.sweep_stale()
                except Exception:  # noqa: BLE001
                    logger.exception('僵尸任务清扫失败')
                last_sweep = time.monotonic()

            # 用短睡眠切片，让 SIGTERM 能在一秒内被响应
            deadline = time.monotonic() + interval
            while not stopping and time.monotonic() < deadline:
                time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))

        self.stdout.write('worker 已退出')
