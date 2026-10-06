"""Django Ninja 全局异常处理器：将异常转换为统一格式的 JSON 错误。"""
import logging

from django.core.exceptions import ValidationError
from django.http import HttpRequest, JsonResponse
from ninja import NinjaAPI
from ninja.errors import HttpError

logger = logging.getLogger(__name__)


def _error_response(code: int, message) -> JsonResponse:
    """构造统一格式的错误响应，code 与 HTTP 状态码一致。"""
    return JsonResponse({'code': code, 'message': message, 'data': None}, status=code)


def _flatten_validation_message(exc: ValidationError) -> str:
    """把 ValidationError 拍平成单行字符串。

    前端统一按字符串展示 ``message``，直接返回 ``message_dict``/``messages``
    会被渲染成 ``[object Object]``，故在此收敛为 ``字段: 文案`` 以 ``; `` 连接。
    """
    if hasattr(exc, 'message_dict') and exc.message_dict:
        parts = []
        for field, messages in exc.message_dict.items():
            for message in messages:
                parts.append(str(message) if field == '__all__' else f'{field}: {message}')
        return '; '.join(parts)
    if exc.messages:
        return '; '.join(str(message) for message in exc.messages)
    return str(exc)


def handle_http_error(request: HttpRequest, exc: HttpError) -> JsonResponse:
    """处理业务抛出的 HttpError（如 400/401/404），返回统一信封。"""
    return _error_response(exc.status_code, exc.message)


def handle_validation_error(request: HttpRequest, exc: ValidationError) -> JsonResponse:
    """处理 Django 模型 / 表单校验错误，返回 400（message 恒为单行字符串）。"""
    return _error_response(400, _flatten_validation_message(exc))


def handle_exception(request: HttpRequest, exc: Exception) -> JsonResponse:
    """兜底处理未知异常，返回 500。

    只回通用文案：``str(exc)`` 可能包含文件绝对路径、数据库约束名、字段名等内部
    信息（归档导入会主动制造大量 IO/格式异常，直接回显等于把内部结构泄露给调用方）。
    细节只写服务端日志。
    """
    logger.exception('未处理异常: %s %s', request.method, request.path)
    return _error_response(500, '服务器内部错误')


def register_exception_handlers(api: NinjaAPI) -> None:
    """注册全局异常处理器到指定的 NinjaAPI 实例。"""
    api.add_exception_handler(HttpError, handle_http_error)  # type: ignore[arg-type]
    api.add_exception_handler(ValidationError, handle_validation_error)  # type: ignore[arg-type]
    api.add_exception_handler(Exception, handle_exception)  # type: ignore[arg-type]
