"""归档异常：区分「整包失败」与「单篇失败」，以及「锁不可用」。"""


class ArchiveError(Exception):
    """归档相关异常基类。"""

    code = 'archive_error'
    http_status = 400

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class PackageError(ArchiveError):
    """整包级错误：不落任何数据，直接 400。"""

    code = 'package_invalid'
    http_status = 400


class ItemError(ArchiveError):
    """单篇级错误：该篇标记 failed，其余条目继续。"""

    code = 'item_invalid'
    http_status = 400


class LimitExceeded(PackageError):
    """超出归档上限（条目数 / 体积 / 压缩比 / 深度 / 路径长度）。"""

    code = 'limit_exceeded'


class LockUnavailable(ArchiveError):
    """导入锁或限流缓存不可用：fail-closed，返回 503。"""

    code = 'lock_unavailable'
    http_status = 503


class ConflictError(ArchiveError):
    """已有导入在进行，或暂存包已被执行过：返回 409。"""

    code = 'conflict'
    http_status = 409


class RateLimitedError(ArchiveError):
    """两次导入间隔过短：返回 429。"""

    code = 'rate_limited'
    http_status = 429
