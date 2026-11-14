"""清扫归档产物：过期的暂存目录、导出/回滚 zip 与对应数据库行。

为什么需要独立命令：gunicorn 超时杀进程走 SIGABRT/SIGKILL，视图里的 ``finally``
不会执行，因此清理不能只依赖请求路径；容器 entrypoint 与定时任务都应调用它。

顺带回收**已结束超过保留期**的导入任务行（``IMPORT_TASK_RETENTION_DAYS``）：
任务表只增不减会一直膨胀，但它又是排查「昨天那次导入为什么失败」的唯一线索，
所以既不能立即删，也不能永久留。
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from articles.archive import staging
from articles.models import ArticleImportTask

#: 任务行保留天数（失败任务是最常被回看的，统一口径，不做差异化）
IMPORT_TASK_RETENTION_DAYS = 30


class Command(BaseCommand):
    help = '清理过期的文章归档产物（暂存包、导出包、回滚包）与票据行、历史任务行'

    def handle(self, *args, **options):
        removed = staging.sweep()
        cutoff = timezone.now() - timedelta(days=IMPORT_TASK_RETENTION_DAYS)
        # finished_at 为空的终态行（历史脏数据）用 created_at 兜底，否则永远删不掉
        expired_tasks, _ = ArticleImportTask.objects.filter(
            Q(finished_at__lt=cutoff) | Q(finished_at__isnull=True, created_at__lt=cutoff),
            status__in=ArticleImportTask.TERMINAL_STATUSES,
        ).delete()
        summary = (
            '归档清扫完成：暂存目录 {staging}、文件 {files}、'
            '票据行 {tickets}、暂存行 {stagings}、历史任务行 {tasks}'
        ).format(tasks=expired_tasks, **removed)
        self.stdout.write(self.style.SUCCESS(summary))
