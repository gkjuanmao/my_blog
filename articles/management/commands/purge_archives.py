"""清扫归档产物：过期的暂存目录、导出/回滚 zip 与对应数据库行。

为什么需要独立命令：gunicorn 超时杀进程走 SIGABRT/SIGKILL，视图里的 ``finally``
不会执行，因此清理不能只依赖请求路径；容器 entrypoint 与定时任务都应调用它。
"""
from django.core.management.base import BaseCommand

from articles.archive import staging


class Command(BaseCommand):
    help = '清理过期的文章归档产物（暂存包、导出包、回滚包）与票据行'

    def handle(self, *args, **options):
        removed = staging.sweep()
        summary = (
            '归档清扫完成：暂存目录 {staging}、文件 {files}、'
            '票据行 {tickets}、暂存行 {stagings}'
        ).format(**removed)
        self.stdout.write(self.style.SUCCESS(summary))
