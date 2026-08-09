"""统一 JSON 响应结构封装。"""
from typing import Any


def success_response(data: Any = None, message: str = 'success', code: int = 200) -> dict:
    """成功响应：code 为 HTTP 状态码（默认 200，创建类接口传 201），data 携带业务数据。"""
    return {'code': code, 'message': message, 'data': data}


def error_response(code: int, message: str) -> dict:
    """失败响应：code 为 HTTP 状态码，data 恒为 None。"""
    return {'code': code, 'message': message, 'data': None}
