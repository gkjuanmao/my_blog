"""清理未被正文引用的内联图片（内联图生命周期的**唯一 owner**）。

安全设计（见 docs/ARTICLE_MARKDOWN_PLAN.md §7.7）：

1. **两遍扫描 + 回收站**：先把候选原子移入 ``MEDIA_ROOT/_inline_trash/<run_id>/``，
   再重新收集一次引用集，把"扫描后被重新引用"的图片**归还**，最后才删除仍未引用的。
2. **fail-closed 守卫（条件收窄）**：仅当「HTML 提取器返回空集 **而** 原始 Markdown
   字面量扫描非空」（= 提取器系统性失效）时中止、绝不删除；两者都空说明**确实没有引用**，
   正常放行（否则正文被清空后回收站会永久无法清理，形成死锁）。
3. **宽限期**：mtime 晚于宽限期的文件从不清理，避免误删"刚上传、正文还没保存"的图。

默认 dry-run，只有 ``--delete`` 才真正执行。
"""
import os
import re
import time
import uuid
from contextlib import suppress

from django.conf import settings
from django.core.management.base import BaseCommand

from articles.images import extract_inline_names, list_inline_files
from articles.models import Article
from articles.rendering import render_markdown


def _inline_dir() -> str:
    return os.path.join(str(settings.MEDIA_ROOT), settings.INLINE_IMAGE_DIR)


def _trash_root() -> str:
    return os.path.join(str(settings.MEDIA_ROOT), settings.INLINE_IMAGE_TRASH_DIR)


def _literal_pattern() -> re.Pattern[str]:
    """原始 Markdown 里的内联图 URL 字面量（与 HTML 提取互为佐证）。"""
    prefix = f'{settings.MEDIA_URL}{settings.INLINE_IMAGE_DIR}/'.lstrip('/')
    return re.compile(re.escape(prefix) + r'([A-Za-z0-9][A-Za-z0-9._-]*)', re.IGNORECASE)


def collect_references() -> tuple[set[str], set[str]]:
    """返回 ``(提取器得到的引用集, 字面量扫描得到的引用集)``。

    一次性把全库正文读进来匹配，避免逐文件 ``content__contains`` 的全表扫描。
    """
    pattern = _literal_pattern()
    extracted: set[str] = set()
    literals: set[str] = set()
    for content in Article.objects.values_list('content', flat=True).iterator():
        if not content:
            continue
        extracted |= extract_inline_names(render_markdown(content))
        literals |= {name.lower() for name in pattern.findall(content)}
    return extracted, literals


class Command(BaseCommand):
    """清理未引用的内联图（默认只报告，不删除）。"""

    help = '清理未被文章正文引用的内联图片（默认 dry-run；--delete 才真正删除）'

    def add_arguments(self, parser) -> None:
        parser.add_argument('--delete', action='store_true', help='真正执行删除（默认只报告）')
        parser.add_argument('--force', action='store_true', help='跳过 fail-closed 守卫')
        parser.add_argument(
            '--grace-hours',
            type=float,
            default=settings.INLINE_IMAGE_PURGE_GRACE_HOURS,
            help='宽限期（小时），mtime 新于此的文件不清理',
        )

    def handle(self, *args, **options) -> None:
        delete: bool = options['delete']
        force: bool = options['force']
        grace_seconds = float(options['grace_hours']) * 3600
        now = time.time()

        extracted, literals = collect_references()
        references = extracted | literals
        files = list_inline_files()

        if files and not extracted and literals and not force:
            self.stderr.write(self.style.ERROR(
                '提取器返回空集但字面量扫描非空，判定为提取器失效：已中止，未删除任何文件'
                '（确认无误可用 --force 强制）。'
            ))
            return

        restored, deleted_old = self._sweep_history(references, grace_seconds, now, delete)

        candidates = []
        for name in files:
            if name in references:
                continue
            path = os.path.join(_inline_dir(), name)
            with suppress(OSError):
                if now - os.path.getmtime(path) < grace_seconds:
                    continue
            candidates.append(name)

        if not delete:
            self.stdout.write(
                f'[dry-run] 引用 {len(references)} 个 / 现存 {len(files)} 个 / '
                f'可回收 {len(candidates)} 个'
            )
            for name in candidates[:50]:
                self.stdout.write(f'  - {name}')
            if restored or deleted_old:
                self.stdout.write(f'  历史回收站：可归还 {restored} / 可删除 {deleted_old}')
            self.stdout.write('未做任何改动（加 --delete 执行）。')
            return

        restored_now, deleted_now = self._process(candidates, grace_seconds, now)
        self.stdout.write(self.style.SUCCESS(
            f'完成：归还 {restored + restored_now}，删除 {deleted_old + deleted_now}，'
            f'跳过 {len(files) - len(candidates)}（仍被引用或未过宽限期）。'
        ))

    # ------------------------------------------------------------------ 内部

    def _move(self, src: str, dst: str) -> None:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.replace(src, dst)

    def _sweep_history(
        self, references: set[str], grace_seconds: float, now: float, delete: bool
    ) -> tuple[int, int]:
        """处理历史回收站：被引用的归还、过宽限期的删除。"""
        root = _trash_root()
        if not os.path.isdir(root):
            return 0, 0
        restored = deletable = 0
        for run_name in sorted(os.listdir(root)):
            run_path = os.path.join(root, run_name)
            if not os.path.isdir(run_path):
                continue
            for name in sorted(os.listdir(run_path)):
                src = os.path.join(run_path, name)
                if not os.path.isfile(src):
                    continue
                if name.lower() in references:
                    restored += 1
                    if delete:
                        self._move(src, os.path.join(_inline_dir(), name))
                    continue
                with suppress(OSError):
                    if now - os.path.getmtime(src) < grace_seconds:
                        continue
                deletable += 1
                if delete:
                    with suppress(OSError):
                        os.unlink(src)
            if delete:
                with suppress(OSError):
                    os.rmdir(run_path)
        return restored, deletable

    def _process(
        self, candidates: list[str], grace_seconds: float, now: float
    ) -> tuple[int, int]:
        """把候选移入回收站 → 二次收集引用并归还 → 删除仍未引用的。"""
        run_dir = os.path.join(_trash_root(), uuid.uuid4().hex)
        moved: dict[str, str] = {}
        for name in candidates:
            dst = os.path.join(run_dir, name)
            self._move(os.path.join(_inline_dir(), name), dst)
            moved[name] = dst

        # pass-2：扫描后可能有人保存了引用这些图的新正文
        extracted2, literals2 = collect_references()
        references2 = extracted2 | literals2

        restored = deleted = 0
        for name, trash_path in moved.items():
            if name in references2:
                self._move(trash_path, os.path.join(_inline_dir(), name))
                restored += 1
                continue
            if now - os.path.getmtime(trash_path) < grace_seconds:
                self._move(trash_path, os.path.join(_inline_dir(), name))
                continue
            with suppress(OSError):
                os.unlink(trash_path)
                deleted += 1
        with suppress(OSError):
            os.rmdir(run_dir)
        return restored, deleted
