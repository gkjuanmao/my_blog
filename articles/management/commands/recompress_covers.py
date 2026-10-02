"""把存量封面重新压缩为 WebP（默认 dry-run，``--apply`` 才写回）。

封面压缩是后续才引入的能力：在此之前上传/导入的封面都是**原样存储**的，
常见 3~4MB 的 JPEG —— 而详情页只是把封面当题图，这是单篇流量里最大的一块。

本命令对存量封面跑一遍新的 ``process_cover``：已达标的（WebP、最长边合格、
无元数据）会被判定为"字节不变"而跳过，因此**可以反复执行**，不会重复损失画质。
"""
from contextlib import suppress

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

from articles.covers import CoverError, ProcessedCover
from articles.covers import process_cover as process_cover_image
from articles.images import extension_of
from articles.models import Article, cover_upload_path


def _kb(size: int) -> str:
    return f'{size / 1024:.0f} KB'


class Command(BaseCommand):
    """重压存量封面（默认只报告，不写回）。"""

    help = '把存量封面重新压缩为 WebP（默认 dry-run；--apply 才真正替换）'

    def add_arguments(self, parser) -> None:
        parser.add_argument('--apply', action='store_true', help='真正写回替换（默认只报告）')
        parser.add_argument('--limit', type=int, default=0, help='最多处理多少篇（0 = 全部）')

    def handle(self, *args, **options) -> None:
        apply: bool = options['apply']
        limit: int = options['limit']

        queryset = Article.objects.exclude(cover_image='').order_by('pk')
        if limit:
            queryset = queryset[:limit]

        before = after = 0
        changed: list[tuple[int, str, int, int]] = []
        skipped = failed = 0

        for article in queryset:
            name = article.cover_image.name
            if not name or not default_storage.exists(name):
                self.stderr.write(f'#{article.pk} 封面文件缺失，跳过：{name}')
                failed += 1
                continue

            with default_storage.open(name, 'rb') as handle:
                raw = handle.read()
            try:
                result = process_cover_image(
                    raw, extension_of(name), max_pixels=settings.COVER_MAX_PIXELS
                )
            except CoverError as exc:
                self.stderr.write(f'#{article.pk} 处理失败：{exc}')
                failed += 1
                continue

            before += len(raw)
            after += len(result.data)
            if result.data == raw:
                skipped += 1
                continue

            changed.append((article.pk, article.title, len(raw), len(result.data)))
            if apply:
                self._replace(article, result)

        self._report(apply, changed, skipped, failed, before, after)

    # ------------------------------------------------------------------ 内部

    def _replace(self, article: Article, result: ProcessedCover) -> None:
        """写入新封面并回收旧文件（先落新盘、保存成功后再删旧）。"""
        old_name = article.cover_image.name
        article.cover_image.save(
            cover_upload_path(article, f'cover.{result.ext}'),
            ContentFile(result.data),
            save=False,
        )
        article.cover_image_sha256 = result.sha256
        # 不含 updated_at：这是运维批量操作，不应把所有文章的"更新时间"刷新一遍
        article.save(update_fields=['cover_image', 'cover_image_sha256'])
        if old_name and old_name != article.cover_image.name:
            with suppress(OSError):
                default_storage.delete(old_name)

    def _report(
        self,
        apply: bool,
        changed: list[tuple[int, str, int, int]],
        skipped: int,
        failed: int,
        before: int,
        after: int,
    ) -> None:
        for pk, title, old_size, new_size in changed:
            ratio = (1 - new_size / old_size) * 100 if old_size else 0
            self.stdout.write(
                f'  #{pk} {title}: {_kb(old_size)} → {_kb(new_size)}（-{ratio:.0f}%）'
            )

        saved = before - after
        headline = f'待重压 {len(changed)} 篇 / 已达标 {skipped} 篇 / 失败 {failed} 篇'
        if changed:
            headline += f'；合计 {_kb(before)} → {_kb(after)}，可省 {_kb(saved)}'

        if apply:
            self.stdout.write(self.style.SUCCESS(f'完成：{headline}'))
        else:
            self.stdout.write(f'[dry-run] {headline}')
            self.stdout.write('未做任何改动（加 --apply 执行）。')
