#!/usr/bin/env python
"""生成地名联想用的 ``common/geo/data/areas.json``。

数据来源（都锁死版本号，不会静默漂移）：

- 中国省/市/区县：``china-division@2.7.0`` 的 ``dist/pca-code.json``（含行政区划代码）
- 港澳台：同包的 ``dist/HK-MO-TW.json``（结构与内地不同，单独合并）
- 国家/地区：``i18n-iso-countries@7.11.0`` 的 ``langs/zh.json``（ISO 3166-1 中文名）

为什么要预生成而不是运行期读原始数据：原始数据里直辖市、省直辖县级行政区划
都挂了一个「市辖区 / 县 / 省直辖县级行政区划」的占位市级节点，运行期每次都要
判一遍既费事又容易漏；这里在构建期一次性摊平成「label + 层级」。

落盘格式是 ``[[label, code, level], ...]``：本地名（末段）和检索路径都能由
label 现算，不重复存，文件 278KB（gzip 40KB）。

用法：

    uv run python scripts/build_geo_data.py            # 从 unpkg 下载
    uv run python scripts/build_geo_data.py --src DIR  # 用本地已下载的三个 json

生成后需要提交 ``common/geo/data/areas.json``。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT = REPO_ROOT / 'common' / 'geo' / 'data' / 'areas.json'

PACKAGE_VERSION = 'china-division@2.7.0'
COUNTRY_PACKAGE = 'i18n-iso-countries@7.11.0'
SOURCES = {
    'pca-code.json': f'https://unpkg.com/{PACKAGE_VERSION}/dist/pca-code.json',
    'hkmotw.json': f'https://unpkg.com/{PACKAGE_VERSION}/dist/HK-MO-TW.json',
    'countries-zh.json': f'https://unpkg.com/{COUNTRY_PACKAGE}/langs/zh.json',
}

# 原始数据里这些「市级」节点其实是占位，展开后不应出现在地名里
PLACEHOLDER_CITIES = frozenset(
    {'市辖区', '县', '省直辖县级行政区划', '自治区直辖县级行政区划'}
)

# 港澳台：数据里是「特别行政区 / 省」的全称，展示时按「中国香港 / 中国澳门 / 中国台湾」
HK_MO_TW_NAMES = {
    '香港特别行政区': ('香港', '810000'),
    '澳门特别行政区': ('澳门', '820000'),
    '台湾省': ('台湾', '710000'),
}

# 中国（含港澳台）由上面两份区划数据负责，国家清单里要去掉，否则会多出一条「中国台湾」
COUNTRY_EXCLUDE = frozenset({'CN', 'HK', 'MO', 'TW'})

#: 单条地名的落盘格式：``[label, code, level]``
Entry = list[str]


def local_name(label: str) -> str:
    """取 label 的本地名（末段），去掉港澳台前缀里的「中国」。

    与 ``common/geo/search.py`` 的运行期实现保持一致；这里用于构建期自检。
    """
    name = label.split(' · ')[-1]
    return name[2:] if name.startswith('中国') else name


def area(label: str, code: str, level: str, name: str = '') -> Entry:
    """构造一条地名条目；``name`` 只用于构建期断言，不落盘。"""
    if name and local_name(label) != name:
        raise ValueError(f'label 末段与 name 不一致：{label} / {name}')
    return [label, code, level]


def build_mainland(data: list[dict[str, Any]]) -> list[Entry]:
    """省 / 市 / 区县三级；占位市级节点被透明折叠。"""
    items: list[Entry] = []
    for province in data:
        p_name = province['name']
        items.append(area(f'中国 · {p_name}', province['code'], 'province', p_name))
        for city in province.get('children') or []:
            c_name = city['name']
            districts = city.get('children') or []
            if c_name in PLACEHOLDER_CITIES:
                # 直辖市（市辖区 / 县）、省直辖县级行政区划：市级只是占位，直接出第三段
                for district in districts:
                    items.append(
                        area(
                            f'中国 · {p_name} · {district["name"]}',
                            district['code'],
                            'district',
                            district['name'],
                        )
                    )
                continue
            items.append(area(f'中国 · {p_name} · {c_name}', city['code'], 'city', c_name))
            for district in districts:
                items.append(
                    area(
                        f'中国 · {p_name} · {c_name} · {district["name"]}',
                        district['code'],
                        'district',
                        district['name'],
                    )
                )
    return items


def build_hk_mo_tw(data: dict[str, dict[str, list[str]]]) -> list[Entry]:
    """港澳台：结构与内地不同，直接按「地区 / 分区 / 区」三段展开。

    区一级没有 GB 编码，``code`` 留空——宁可空着，也不编一个假代码出来。
    """
    items: list[Entry] = []
    for full_name, groups in data.items():
        short, code = HK_MO_TW_NAMES[full_name]
        items.append(area(f'中国{short}', code, 'province', short))
        for group, districts in groups.items():
            items.append(area(f'中国{short} · {group}', '', 'city', group))
            for district in districts:
                items.append(area(f'中国{short} · {group} · {district}', '', 'district', district))
    return items


def build_countries(data: dict[str, Any]) -> list[Entry]:
    """国家/地区：只到国家一级，城市靠手输（离线数据没有，地图 API 也不覆盖国外）。"""
    items: list[Entry] = []
    for code, name in (data.get('countries') or {}).items():
        if code in COUNTRY_EXCLUDE:
            continue
        items.append(area(name, code, 'country', name))
    return items


def load_source(name: str, src_dir: Path | None) -> Any:
    if src_dir is not None:
        return json.loads((src_dir / name).read_text(encoding='utf-8'))
    with urllib.request.urlopen(SOURCES[name], timeout=60) as response:  # noqa: S310
        return json.loads(response.read().decode('utf-8'))


def main() -> int:
    parser = argparse.ArgumentParser(description='生成地名联想数据文件')
    parser.add_argument('--src', type=Path, default=None, help='三个原始 json 所在目录')
    args = parser.parse_args()

    mainland = load_source('pca-code.json', args.src)
    hkmotw = load_source('hkmotw.json', args.src)
    countries = load_source('countries-zh.json', args.src)

    items = build_mainland(mainland) + build_hk_mo_tw(hkmotw) + build_countries(countries)

    labels = [item[0] for item in items]
    if len(set(labels)) != len(labels):
        duplicated = sorted({label for label in labels if labels.count(label) > 1})
        print(f'存在重复 label：{duplicated[:10]}', file=sys.stderr)
        return 1

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(items, ensure_ascii=False, separators=(',', ':')),
        encoding='utf-8',
    )

    by_level: dict[str, int] = {}
    for _, _, level in items:
        by_level[level] = by_level.get(level, 0) + 1
    print(f'写入 {OUTPUT}（{OUTPUT.stat().st_size:,} 字节）')
    print('分布：' + ', '.join(f'{k}={v}' for k, v in sorted(by_level.items())))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
