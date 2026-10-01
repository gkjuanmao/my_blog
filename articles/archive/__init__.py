"""文章归档（导入 / 导出）实现包。

模块划分：
- ``errors``    异常与错误码
- ``limits``    上限读取（导出/导入共用）与磁盘空间预检
- ``format``    归档格式常量与 JSON 序列化
- ``validate``  压缩包与条目校验、媒体读取
- ``export``    打包、预估、可回导性校验
- ``locks``     导入串行锁与最小间隔（缓存实现，fail-closed）
- ``staging``   暂存与票据生命周期
- ``planner``   匹配与动作决策（预检与执行共用同一份产出）
- ``importer``  执行、媒体落盘与失败补偿
"""

from .errors import (
    ArchiveError,
    ItemError,
    LockUnavailable,
    PackageError,
)

__all__ = [
    'ArchiveError',
    'ItemError',
    'LockUnavailable',
    'PackageError',
]
