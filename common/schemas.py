"""统一响应信封与分页结构 Schema，供 Swagger/OpenAPI 文档生成具体结构。"""
from ninja import Schema


class ApiResponse[T](Schema):
    """统一响应信封：code 为 HTTP 状态码，message 为提示信息，data 携带业务数据。"""

    code: int
    message: str
    data: T | None = None


class PageData[T](Schema):
    """分页数据：items 为当前页数据，total 为总数，page/page_size 为当前页码与每页数量。"""

    items: list[T]
    total: int
    page: int
    page_size: int
