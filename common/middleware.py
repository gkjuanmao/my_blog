"""为公开列表接口补 ``Cache-Control`` 的中间件。"""
from django.http import HttpRequest, HttpResponse

# 仅精确匹配三个公开列表路径：不能波及带鉴权的 /api/v1/admin/**，
# 也不能波及会写阅读量的文章详情 /api/v1/articles/{slug}/。
PUBLIC_CACHE_PATHS = frozenset(
    {
        '/api/v1/articles/',
        '/api/v1/categories/',
        '/api/v1/tags/',
    }
)
PUBLIC_CACHE_MAX_AGE = 60


class PublicCacheControlMiddleware:
    """对公开列表 GET 的成功响应补 ``Cache-Control: public, max-age=60``。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        if (
            request.method == 'GET'
            and request.path in PUBLIC_CACHE_PATHS
            and response.status_code == 200
        ):
            response['Cache-Control'] = f'public, max-age={PUBLIC_CACHE_MAX_AGE}'
        return response
