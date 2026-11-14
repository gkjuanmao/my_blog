"""预检/执行共用的报告结构。

抽成独立模块的原因：预检（HTTP 请求内）与异步执行（worker 进程内）都要产出
**同构**的报告，否则前端得为两条链路各写一套渲染。同时避免
``articles.api`` ↔ ``articles.archive.tasks`` 的循环导入。
"""
from . import format as archive_format
from .planner import Plan


def package_info_dict(info) -> dict:
    """报告里的包级信息（只暴露白名单字段，不透传原始异常文本）。"""
    return {
        'entries': info.entries_count,
        'bytes_uncompressed': info.uncompressed_bytes,
        'sha256': info.sha256,
    }


def plan_report(plan: Plan, *, dry_run: bool, package: dict) -> dict:
    """预检与执行统一的报告骨架（同一 planner 产出）。"""
    return {
        'dry_run': dry_run,
        'schema': archive_format.REPORT_SCHEMA,
        'package': package,
        'totals': plan.totals(),
        'items': [item.to_dict() for item in plan.items],
    }
