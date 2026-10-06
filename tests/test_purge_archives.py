"""``purge_archives`` 管理命令测试（TEST-05）。

该命令由容器 entrypoint 每次启动与 ``blog.sh purge`` 调用，负责回收：
过期暂存目录、过期票据文件、以及**没有 DB 行对应**的孤儿产物（文件/暂存目录，>1h）。
"""
import os
import time
import uuid
from datetime import timedelta
from pathlib import Path

from django.core.management import call_command
from django.utils import timezone

from articles.archive import staging
from articles.models import ArchiveStaging, ArchiveTicket


def _age(path: Path, *, hours: float) -> None:
    """把文件/目录的 mtime 回拨若干小时（模拟陈旧孤儿产物）。"""
    stamp = time.time() - hours * 3600
    os.utime(path, (stamp, stamp))


def _make_staging(user, *, expires_in: timedelta, lease_in: timedelta | None = None):
    sid = uuid.uuid4()
    directory = staging.create_staging_dir(sid)
    (directory / 'package.zip').write_bytes(b'PK\x03\x04payload')
    row = ArchiveStaging.objects.create(
        id=sid,
        user=user,
        dir=staging.rel_path(directory),
        sha256='0' * 64,
        bytes=11,
        entries=1,
        expires_at=timezone.now() + expires_in,
        lease_until=(timezone.now() + lease_in) if lease_in else None,
    )
    return row, directory


def _make_ticket(user, *, expires_in: timedelta, relative: str = 'exports/pack.zip'):
    path = staging.archive_root() / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'PK\x03\x04ticket')
    row = ArchiveTicket.objects.create(
        user=user,
        kind=ArchiveTicket.Kind.EXPORT,
        path=staging.rel_path(path),
        filename='pack.zip',
        bytes=11,
        expires_at=timezone.now() + expires_in,
    )
    return row, path


class TestExpiredRows:
    def test_expired_staging_dir_and_row_removed(self, user):
        row, directory = _make_staging(user, expires_in=timedelta(seconds=-1))

        call_command('purge_archives')

        assert not directory.exists()
        assert not ArchiveStaging.objects.filter(id=row.id).exists()

    def test_staging_with_active_lease_kept(self, user):
        """带"使用中租约"的暂存目录即使已过期也不能删（避免删掉正在 commit 的包）。"""
        row, directory = _make_staging(
            user, expires_in=timedelta(seconds=-1), lease_in=timedelta(minutes=5)
        )

        call_command('purge_archives')

        assert directory.exists()
        assert ArchiveStaging.objects.filter(id=row.id).exists()

    def test_unexpired_staging_kept(self, user):
        row, directory = _make_staging(user, expires_in=timedelta(minutes=5))

        call_command('purge_archives')

        assert directory.exists()
        assert ArchiveStaging.objects.filter(id=row.id).exists()

    def test_expired_ticket_file_and_row_removed(self, user):
        row, path = _make_ticket(user, expires_in=timedelta(seconds=-1))

        call_command('purge_archives')

        assert not path.exists()
        assert not ArchiveTicket.objects.filter(id=row.id).exists()

    def test_unexpired_ticket_kept(self, user):
        row, path = _make_ticket(user, expires_in=timedelta(minutes=5))

        call_command('purge_archives')

        assert path.exists()
        assert ArchiveTicket.objects.filter(id=row.id).exists()

    def test_expired_row_without_file_still_dropped(self, user):
        """文件已被手工删掉时，过期行仍应被清理（不能因文件缺失而残留）。"""
        row, path = _make_ticket(user, expires_in=timedelta(seconds=-1))
        path.unlink()

        call_command('purge_archives')

        assert not ArchiveTicket.objects.filter(id=row.id).exists()


class TestOrphans:
    def test_old_orphan_export_file_removed(self, db, archive_root):
        orphan = archive_root / 'exports' / 'orphan.zip'
        orphan.parent.mkdir(parents=True, exist_ok=True)
        orphan.write_bytes(b'PK\x03\x04orphan')
        _age(orphan, hours=2)

        call_command('purge_archives')

        assert not orphan.exists()

    def test_fresh_orphan_file_kept(self, db, archive_root):
        """1 小时宽限期内不删，避免竞态误删刚写完但还没登记行的产物。"""
        orphan = archive_root / 'rollbacks' / 'fresh.zip'
        orphan.parent.mkdir(parents=True, exist_ok=True)
        orphan.write_bytes(b'PK\x03\x04fresh')

        call_command('purge_archives')

        assert orphan.exists()

    def test_old_orphan_staging_dir_removed(self, db, archive_root):
        orphan = archive_root / 'staging' / 'no-row-dir'
        orphan.mkdir(parents=True, exist_ok=True)
        _age(orphan, hours=2)

        call_command('purge_archives')

        assert not orphan.exists()

    def test_old_file_with_matching_row_is_kept(self, user):
        """有有效票据行引用的旧文件不算孤儿，即便 mtime 很旧也不能删。"""
        _row, path = _make_ticket(user, expires_in=timedelta(minutes=5))
        _age(path, hours=2)

        call_command('purge_archives')

        assert path.exists()


class TestCommandOutput:
    def test_reports_summary(self, user, capsys):
        _make_staging(user, expires_in=timedelta(seconds=-1))

        call_command('purge_archives')

        out = capsys.readouterr().out
        assert '归档清扫完成' in out
        assert '暂存目录 1' in out
        assert '暂存行 1' in out
