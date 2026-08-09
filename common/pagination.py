"""自定义分页器：配合 Django Ninja 使用，返回 items/total/page/page_size。"""
from typing import Any

from ninja import Field, Schema
from ninja.pagination import PaginationBase


class CustomPagination(PaginationBase):
    """分页参数：页码从 1 开始，每页 1-100 条。"""

    class Input(Schema):
        page: int = Field(1, ge=1, description='页码')
        page_size: int = Field(10, ge=1, le=100, description='每页数量')

    class Output(Schema):
        items: list[Any]
        total: int
        page: int
        page_size: int

    items_attribute = 'items'

    def paginate_queryset(self, queryset, pagination: Input, request, **params: Any) -> dict:
        # 兼容 QuerySet 与已序列化的 list，先统计总数再切片取当前页
        try:
            total = queryset.count()
        except (AttributeError, TypeError):
            total = len(queryset)
        start = (pagination.page - 1) * pagination.page_size
        end = start + pagination.page_size
        return {
            'items': queryset[start:end],
            'total': total,
            'page': pagination.page,
            'page_size': pagination.page_size,
        }
