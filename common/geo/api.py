"""地名检索接口：``GET /api/v1/geo/search/``。

只有一个端点，供后台文章编辑台的地点输入框做联想。公开站点不用它，
所以鉴权用 ``StaffJWTAuth``——和文章管理端点同一口径，普通登录用户拿不到。
"""
from django.http import HttpRequest
from ninja import Query, Router, Schema

from common.responses import success_response
from common.schemas import ApiResponse
from users.authentication import StaffJWTAuth

from .search import DEFAULT_LIMIT, MAX_LIMIT, search_areas

router = Router(tags=['地名'])

staff_auth = StaffJWTAuth()


class GeoAreaOut(Schema):
    """一条地名候选。"""

    label: str
    #: 行政区划代码；港澳台的区一级没有 GB 编码，为空串
    code: str
    #: province / city / district / country
    level: str


class GeoSearchOut(Schema):
    """地名检索结果。"""

    items: list[GeoAreaOut]


@router.get('/geo/search/', response=ApiResponse[GeoSearchOut], auth=staff_auth)
def search_geo(
    request: HttpRequest,
    q: str = '',
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
) -> dict:
    """按关键词检索中国省/市/区县以及国家。

    关键词少于 2 个字时返回空列表（单字会命中上千条，对填写没有帮助），
    前端据此可以按「有没有候选」来决定是否提示手输。
    """
    areas = search_areas(q, limit)
    return success_response(
        {
            'items': [
                {'label': area.label, 'code': area.code, 'level': area.level}
                for area in areas
            ]
        }
    )
