"""地名检索 API 测试：鉴权、排序口径、行政区划数据的已知坑、境外兜底契约。

口径：
- 只给 staff（后台编辑台用），匿名 401、普通登录用户 403；
- 排序必须让搜「南京」第一条是南京市，而不是先冒出一堆街道/区县；
- 数据里直辖市的「市辖区」、省直辖县的「省直辖县级行政区划」是占位节点，
  不能出现在 label 里；
- 境外地点**不在这里支持**：搜不到就返回空，由前端提示「直接手输」。
  这条是契约，别为了「友好」改成模糊匹配，否则会把自由文本改写坏。
"""
import json

from common.geo.search import DATA_FILE, search_areas

BASE = '/api/v1/geo/search/'


def labels(response) -> list[str]:
    return [item['label'] for item in response.json()['data']['items']]


# --------------------------------------------------------------------------- 鉴权


def test_geo_001_anonymous_rejected(api_client):
    """GEO-001 匿名访问 401（地名联想是后台接口）。"""
    response = api_client.get(BASE, {'q': '南京'})

    assert response.status_code == 401


def test_geo_002_plain_user_forbidden(api_client, plain_header):
    """GEO-002 非 staff 登录用户 403。"""
    response = api_client.get(BASE, {'q': '南京'}, **plain_header)

    assert response.status_code == 403


# --------------------------------------------------------------------------- 结构


def test_geo_003_item_shape(api_client, auth_header):
    """GEO-003 返回 label / code / level 三个字段，层级取值在约定集合内。"""
    response = api_client.get(BASE, {'q': '南京'}, **auth_header)

    assert response.status_code == 200
    items = response.json()['data']['items']
    assert items
    first = items[0]
    assert set(first) == {'label', 'code', 'level'}
    assert first['label'] == '中国 · 江苏省 · 南京市'
    assert first['code'] == '3201'
    assert first['level'] == 'city'


# --------------------------------------------------------------------------- 排序


def test_geo_004_city_before_districts(api_client, auth_header):
    """GEO-004 搜「南京」第一条是市，后面才是它下辖的区（浅层优先）。"""
    response = api_client.get(BASE, {'q': '南京'}, **auth_header)

    found = labels(response)
    assert found[0] == '中国 · 江苏省 · 南京市'
    assert all(label.startswith('中国 · 江苏省 · 南京市') for label in found)
    assert any(label.endswith('玄武区') for label in found)


def test_geo_005_district_only(api_client, auth_header):
    """GEO-005 搜「玄武」只出玄武区。"""
    response = api_client.get(BASE, {'q': '玄武'}, **auth_header)

    assert labels(response) == ['中国 · 江苏省 · 南京市 · 玄武区']


def test_geo_006_province_first(api_client, auth_header):
    """GEO-006 搜「江苏」第一条是省，再往下才是各市。"""
    found = labels(api_client.get(BASE, {'q': '江苏'}, **auth_header))

    assert found[0] == '中国 · 江苏省'
    assert found[1].startswith('中国 · 江苏省 · ')


def test_geo_007_multi_token_keyword(api_client, auth_header):
    """GEO-007 「云南 · 大理」「云南大理」都要能命中（老习惯 + 人自然的写法）。"""
    for keyword in ('云南 · 大理', '云南 大理', '云南大理'):
        found = labels(api_client.get(BASE, {'q': keyword}, **auth_header))
        assert found[0] == '中国 · 云南省 · 大理白族自治州', keyword


def test_geo_007b_natural_input_without_suffix(api_client, auth_header):
    """GEO-007B 不带「省 / 市 / 区」后缀的自然输入也要命中（用户不会照着全称敲）。"""
    cases = {
        '江苏南京': '中国 · 江苏省 · 南京市',
        '北京东城': '中国 · 北京市 · 东城区',
        '内蒙古呼和浩特': '中国 · 内蒙古自治区 · 呼和浩特市',
    }
    for keyword, expected in cases.items():
        found = labels(api_client.get(BASE, {'q': keyword}, **auth_header))
        assert found[0] == expected, keyword


def test_geo_008_china_prefix_is_optional(api_client, auth_header):
    """GEO-008 带不带「中国」前缀结果一致。"""
    with_prefix = labels(api_client.get(BASE, {'q': '中国 · 江苏'}, **auth_header))
    without = labels(api_client.get(BASE, {'q': '江苏'}, **auth_header))

    assert with_prefix == without


# --------------------------------------------------------------------------- 边界


def test_geo_009_single_char_returns_empty(api_client, auth_header):
    """GEO-009 单字不检索：会命中上千条，对填写没帮助。"""
    assert api_client.get(BASE, {'q': '南'}, **auth_header).json()['data']['items'] == []


def test_geo_010_empty_keyword_returns_empty(api_client, auth_header):
    """GEO-010 空关键词返回空列表而不是报错（前端清空输入框时会走到）。"""
    assert api_client.get(BASE, {'q': ''}, **auth_header).json()['data']['items'] == []


def test_geo_011_limit_applied(api_client, auth_header):
    """GEO-011 limit 生效。"""
    response = api_client.get(BASE, {'q': '江苏', 'limit': 3}, **auth_header)

    assert len(response.json()['data']['items']) == 3


def test_geo_012_limit_out_of_range(api_client, auth_header):
    """GEO-012 limit 超过上限（50）由 ninja 校验拦下，返回 422。"""
    assert api_client.get(BASE, {'q': '江苏', 'limit': 999}, **auth_header).status_code == 422
    assert api_client.get(BASE, {'q': '江苏', 'limit': 0}, **auth_header).status_code == 422


# --------------------------------------------------------------------------- 数据坑


def test_geo_013_municipality_has_no_placeholder(api_client, auth_header):
    """GEO-013 直辖市：北京直接到区，label 里不能出现「市辖区」。"""
    found = labels(api_client.get(BASE, {'q': '北京'}, **auth_header))

    assert found[0] == '中国 · 北京市'
    assert '中国 · 北京市 · 东城区' in found
    assert all('市辖区' not in label for label in found)


def test_geo_014_province_direct_county(api_client, auth_header):
    """GEO-014 省直辖县级行政区划：济源市直接挂在河南省下，不带占位层级。"""
    found = labels(api_client.get(BASE, {'q': '济源'}, **auth_header))

    assert found == ['中国 · 河南省 · 济源市']


def test_geo_015_hk_mo_tw_naming(api_client, auth_header):
    """GEO-015 港澳台用「中国香港 / 中国澳门 / 中国台湾」，不套「中国 · 省」两级。"""
    hk = labels(api_client.get(BASE, {'q': '香港', 'limit': 50}, **auth_header))

    assert hk[0] == '中国香港'
    assert '中国香港 · 香港岛 · 中西区' in hk
    assert all('特别行政区' not in label for label in hk)

    tw = labels(api_client.get(BASE, {'q': '台北'}, **auth_header))
    assert tw[0] == '中国台湾 · 台北市'


def test_geo_016_data_file_is_clean():
    """GEO-016 数据文件自检：无占位层级、无「中国 · 香港特别行政区」这类错拼。"""
    rows = json.loads(DATA_FILE.read_text(encoding='utf-8'))

    assert len(rows) > 3000
    for label, _code, level in rows:
        assert level in {'province', 'city', 'district', 'country'}, level
        if level != 'country':
            # 国内（含港澳台）一律以「中国」开头；国家条目就是国名本身
            assert label.startswith('中国'), label
        assert '市辖区' not in label, label
        assert '省直辖县级行政区划' not in label, label
        assert '自治区直辖县级行政区划' not in label, label
    assert len({row[0] for row in rows}) == len(rows)  # label 唯一


# --------------------------------------------------------------------------- 境外兜底


def test_geo_017_country_level_available(api_client, auth_header):
    """GEO-017 国家能查到（选完自动补分隔符，再手打城市）。"""
    response = api_client.get(BASE, {'q': '瑞士'}, **auth_header)

    items = response.json()['data']['items']
    assert items == [{'label': '瑞士', 'code': 'CH', 'level': 'country'}]


def test_geo_018_foreign_free_text_returns_empty(api_client, auth_header):
    """GEO-018 境外自由文本查不到就返回空——这是契约，前端据此提示「直接手输」。

    「罗马」不在此列：它会命中国家「罗马尼亚」（子串命中），但**不会**返回任何
    中国地名，前端照样得让用户自己确认——所以这里只断言没有中国区划被误选。
    """
    for keyword in ('瑞士蒙特勒 日内瓦', '意大利佛罗伦萨 比萨'):
        response = api_client.get(BASE, {'q': keyword}, **auth_header)
        assert response.json()['data']['items'] == [], keyword

    rome = api_client.get(BASE, {'q': '罗马'}, **auth_header).json()['data']['items']
    assert all(item['level'] == 'country' for item in rome)


# --------------------------------------------------------------------------- 纯函数


def test_geo_019_search_areas_ranking():
    """GEO-019 纯函数层：同名前缀时浅层优先（大理：州 在 市 之前）。"""
    found = [area.label for area in search_areas('大理')]

    assert found[0] == '中国 · 云南省 · 大理白族自治州'
    assert found[1] == '中国 · 云南省 · 大理白族自治州 · 大理市'


def test_geo_020_search_areas_is_deterministic():
    """GEO-020 同一关键词两次结果一致（排序键含 label，避免同分随机）。"""
    assert [a.label for a in search_areas('贵州')] == [a.label for a in search_areas('贵州')]
