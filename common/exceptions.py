"""Django Ninja 全局异常处理器：将异常转换为统一格式的 JSON 错误。"""
from django.core.exceptions import ValidationError
from django.http import HttpRequest, JsonResponse
from ninja import NinjaAPI
from ninja.errors import HttpError


def _error_response(code: int, message) -> JsonResponse:
    """构造统一格式的错误响应，code 与 HTTP 状态码一致。"""
    return JsonResponse({'code': code, 'message': message, 'data': None}, status=code)


def handle_http_error(request: HttpRequest, exc: HttpError) -> JsonResponse:
    """处理业务抛出的 HttpError（如 400/401/404），返回统一信封。"""
    return _error_response(exc.status_code, exc.message)


def handle_validation_error(request: HttpRequest, exc: ValidationError) -> JsonResponse:
    """处理 Django 模型 / 表单校验错误，返回 400。"""
    if hasattr(exc, 'message_dict') and exc.message_dict:
        return _error_response(400, exc.message_dict)
    if exc.messages:
        return _error_response(400, exc.messages)
    return _error_response(400, str(exc))


def handle_exception(request: HttpRequest, exc: Exception) -> JsonResponse:
    """兜底处理未知异常，返回 500。"""
    return _error_response(500, str(exc))


def register_exception_handlers(api: NinjaAPI) -> None:
    """注册全局异常处理器到指定的 NinjaAPI 实例。"""
    api.add_exception_handler(HttpError, handle_http_error)  # type: ignore[arg-type]
    api.add_exception_handler(ValidationError, handle_validation_error)  # type: ignore[arg-type]
    api.add_exception_handler(Exception, handle_exception)  # type: ignore[arg-type]
