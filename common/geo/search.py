"""地名检索：中国省/市/区县 + 国家，纯内存，无数据库、无迁移。

数据文件 ``data/areas.json`` 由 ``scripts/build_geo_data.py`` 生成（格式见该脚本）。
为什么放服务端而不是打包进前端：4000 条 278KB，塞进首屏不划算；放服务端后
前端只多一次内网请求（几毫秒），数据还能独立更新。
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

DATA_FILE = Path(__file__).resolve().parent / 'data' / 'areas.json'

#: 层级从浅到深：同分时浅层优先，搜「南京」先给市、再给区
LEVEL_ORDER = {'province': 0, 'city': 1, 'district': 2, 'country': 3}

#: 少于这个长度不检索：单字会命中上千条，对填写没帮助
MIN_KEYWORD_LENGTH = 2
DEFAULT_LIMIT = 20
MAX_LIMIT = 50


class Area(NamedTuple):
    """一条地名。``path`` 是去掉「中国」前缀、去掉分隔符后的整条路径，用于兜底匹配。"""

    label: str
    code: str
    level: str
    name: str
    path: str
    slim: str


#: 逐段剥掉的行政区划后缀（长后缀必须在前，否则「自治区」会被「区」先啃掉）
ADMIN_SUFFIXES = (
    '特别行政区',
    '自治区',
    '自治州',
    '自治县',
    '自治旗',
    '地区',
    '省',
    '市',
    '区',
    '县',
    '旗',
    '盟',
)


def _strip_suffix(segment: str) -> str:
    for suffix in ADMIN_SUFFIXES:
        if segment.endswith(suffix) and len(segment) > len(suffix):
            return segment[: -len(suffix)]
    return segment


def _to_area(label: str, code: str, level: str) -> Area:
    segments = label.split(' · ')
    name = segments[-1]
    if name.startswith('中国'):
        # 港澳台：label 是「中国香港 · 香港岛 · 中西区」，本地名取「香港」而不是「中国香港」
        name = name[2:]
    # 检索路径不保留「中国」前缀：否则搜「中国」会把 4000 条全部命中
    path = ''.join(segments).removeprefix('中国')
    return Area(
        label=label,
        code=code,
        level=level,
        name=name,
        path=path,
        # 去掉「省 / 市 / 区」这类后缀的路径，专门伺候「江苏南京」「北京东城」这种
        # 不带后缀的自然输入——否则「江苏省南京市」里夹着个「省」字，永远搜不到
        slim=''.join(_strip_suffix(segment) for segment in segments).removeprefix('中国'),
    )


@lru_cache(maxsize=1)
def _entries() -> tuple[Area, ...]:
    """读一次数据并在进程内驻留；约 4000 条，常驻内存 3MB 上下。"""
    rows = json.loads(DATA_FILE.read_text(encoding='utf-8'))
    return tuple(_to_area(label, code, level) for label, code, level in rows)


def normalize_keyword(keyword: str) -> str:
    """去掉空白与分隔符，并剥掉开头的「中国」，让「中国 · 江苏」「中国江苏」等价。"""
    compact = ''.join(keyword.split()).replace('·', '')
    return compact.removeprefix('中国')


def split_keyword(keyword: str) -> list[str]:
    """按空格与「·」切词，并丢掉开头的「中国」。

    老文章的写法是「云南 · 大理」，用户很可能照着敲；而数据里的路径是连续的
    「云南省大理白族自治州」，整串匹配会落空，所以要按词逐个匹配。
    """
    tokens = [token for token in re.split(r'[·\s]+', keyword.strip()) if token]
    if tokens and tokens[0] == '中国':
        tokens = tokens[1:]
    return tokens


def _rank_name(area: Area, keyword: str) -> int | None:
    """只看本地名的匹配优先级；不命中返回 None。"""
    if area.name == keyword:
        return 0
    if area.name.startswith(keyword):
        return 1
    if keyword in area.name:
        return 2
    return None


def _in_path(area: Area, text: str) -> bool:
    """路径命中：带后缀的原路径，或去掉行政后缀的路径，任一包含即算。"""
    return text in area.path or text in area.slim


def _rank(area: Area, keyword: str, tokens: list[str]) -> int | None:
    """给命中方式定优先级：本地名越「贴题」越靠前。

    Returns:
        0 名称完全相同 / 1 名称前缀 / 2 名称包含 / 3 仅路径包含；不命中返回 None。
    """
    if len(tokens) > 1:
        # 多词：每个词都要出现在路径里（顺序不限），排序看末词贴不贴题
        if not all(_in_path(area, token) for token in tokens):
            return None
        name_rank = _rank_name(area, tokens[-1])
        return 3 if name_rank is None else name_rank

    if (name_rank := _rank_name(area, keyword)) is not None:
        return name_rank
    if _in_path(area, keyword):
        return 3
    return None


def search_areas(keyword: str, limit: int = DEFAULT_LIMIT) -> list[Area]:
    """按关键词检索地名。

    Args:
        keyword: 用户输入，允许带空格或「·」。
        limit: 返回条数上限，会被夹到 ``[1, MAX_LIMIT]``。

    Returns:
        命中的地名，按「命中方式 → 层级由浅到深 → label 长度 → label」排序，
        保证搜「南京」第一条一定是南京市、搜「玄武」第一条一定是玄武区。
    """
    compact = normalize_keyword(keyword)
    if len(compact) < MIN_KEYWORD_LENGTH:
        return []

    tokens = split_keyword(keyword)
    limit = max(1, min(limit, MAX_LIMIT))
    scored: list[tuple[int, int, int, str, Area]] = []
    for area in _entries():
        rank = _rank(area, compact, tokens)
        if rank is None:
            continue
        scored.append((rank, LEVEL_ORDER[area.level], len(area.label), area.label, area))

    scored.sort(key=lambda row: row[:4])
    return [row[4] for row in scored[:limit]]
