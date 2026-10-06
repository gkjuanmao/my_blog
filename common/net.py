"""请求相关的公共工具。"""
from django.http import HttpRequest


def client_ip(request: HttpRequest) -> str:
    """取真实客户端 IP。

    nginx 以 ``$proxy_add_x_forwarded_for`` 追加真实来源，因此取 X-Forwarded-For
    的**最后一段**（由我们的 nginx 写入）；取第一段会被客户端伪造。
    登录失败限流与阅读量去重共用同一口径，避免两处实现漂移。
    """
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[-1].strip()
    return request.META.get('REMOTE_ADDR', '')
