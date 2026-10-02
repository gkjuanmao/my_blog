"""HTML → Markdown 转换（后台「导入 HTML」）。

用于把手机 App / 第三方导出的 HTML 游记导入为 Markdown 正文。

流水线（顺序不可调换）：

1. **bs4 阶段先处理内联图**：必须早于 nh3 —— nh3 按 ``url_schemes`` 白名单消毒，
   ``data:`` 不在白名单内，base64 图会在转换前就被剥掉 ``src``；
2. **nh3 预清洗**：丢掉 ``script``/``style``/``font``/内联 ``style=`` 等，只保留结构标签，
   否则 markdownify 会把一堆样式垃圾转进 Markdown；
3. **markdownify**：转成 ATX 标题的 Markdown；
4. **规范化空白**（``&nbsp;``、行尾空白、连续空行）。

图片与上传端点共用 ``process_inline_image`` → ``store_inline_image``：base64 内嵌图会被压成
WebP 并按内容寻址落盘（同图自动去重），这是省内网穿透流量的关键一步。
"""
import base64
import binascii
import re
from dataclasses import dataclass, field
from typing import Any, cast

import nh3
from bs4 import BeautifulSoup, Tag
from django.conf import settings
from markdownify import markdownify

from .images import InlineImageError, process_inline_image, store_inline_image
from .rendering import ALLOWED_ATTRIBUTES, ALLOWED_TAGS

# 纯噪声标签：整体删除（含其文本）
_DROP_TAGS = ('script', 'style', 'noscript', 'iframe', 'head', 'meta', 'link')

# 预清洗白名单。注意 nh3 丢标签时**保留文字但丢掉语义**，所以渲染白名单没覆盖的
# b/i/s/strike 等必须补进来，否则 <b> 的加粗会在转换前就没了。
_PRE_TAGS: set[str] = ALLOWED_TAGS | {'b', 'i', 's', 'strike', 'tfoot', 'caption'}

_PRE_ATTRIBUTES: dict[str, set[str]] = {
    **ALLOWED_ATTRIBUTES,
    'th': {'align', 'colspan', 'rowspan'},
    'td': {'align', 'colspan', 'rowspan'},
}

# 预清洗阶段不放行 ``data:``：内联图已在第 1 步换成本地 URL；万一有漏网（例如
# ``srcset`` 里的 base64），这里会连同属性一起剥掉，避免巨串流进 Markdown。
_PRE_URL_SCHEMES: set[str] = {'http', 'https', 'mailto'}

_DATA_URI_RE = re.compile(
    r'^data:(?P<mime>[a-z0-9.+-]+/[a-z0-9.+-]+)?;base64,(?P<payload>.*)$',
    re.IGNORECASE | re.DOTALL,
)
# 与 settings.INLINE_IMAGE_EXTENSIONS 对齐（**不带点**，ext 直接喂给
# process_inline_image）；gif/heic/svg 等一律告警并移除
_MIME_TO_EXT = {
    'image/jpeg': 'jpg',
    'image/jpg': 'jpg',
    'image/png': 'png',
    'image/webp': 'webp',
}

_BLOCK_TAGS = (
    'p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li',
    'blockquote', 'pre', 'table', 'hr', 'section', 'article', 'header', 'footer',
)

# Markdown 的硬换行标记（行尾两个空格）与代码围栏
_HARD_BREAK = '  '
_FENCE_RE = re.compile(r'^\s*(```|~~~)')


class ConvertError(Exception):
    """HTML 无法转换为正文（内容为空或提取不到正文）。"""


@dataclass(frozen=True)
class ConvertResult:
    """转换结果：Markdown 正文、已处理的 base64 内嵌图张数、条目级告警。

    ``images`` 是**处理的引用数**（同一张图出现多次会分别计数），因为内容寻址，
    落盘始终只有一份。
    """

    markdown: str
    images: int
    warnings: list[str] = field(default_factory=list)


def _short(value: str, limit: int = 60) -> str:
    value = value.strip()
    return value if len(value) <= limit else f'{value[:limit]}…'


def _promote_divs(root: Tag) -> None:
    """把「只含行内内容」的 ``<div>`` 提升为 ``<p>``。

    手机便签类导出普遍用裸 ``<div>`` 当段落；nh3 丢掉 ``<div>`` 时只保留文字，
    相邻段落会黏成一行。只提升没有块级后代的 div，避免造出 ``<p><h1>…</h1></p>``
    这类非法嵌套。
    """
    for div in root.find_all('div'):
        if not div.get_text(strip=True):
            continue
        if div.find(_BLOCK_TAGS) is not None:
            continue
        div.name = 'p'


def _attr_str(tag: Tag, name: str) -> str:
    """读取标签属性并归一化成字符串。

    bs4 对 ``class`` 这类多值属性返回 list（类型为 ``str | AttributeValueList``），
    统一成空格连接的字符串，避免直接 ``.strip()`` 类型不安全。
    """
    value = tag.get(name)
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return ' '.join(str(item) for item in value).strip()
    return ''


def _process_images(root: Tag, warnings: list[str]) -> int:
    """把 base64 内嵌图压成 WebP 落盘并改写 ``src``；返回处理的张数（含重复引用）。"""
    stored = 0
    for index, img in enumerate(root.find_all('img'), start=1):
        src = _attr_str(img, 'src')
        alt = _attr_str(img, 'alt')
        title = _attr_str(img, 'title')

        if src.startswith(('http://', 'https://')):
            # 外链图保留原样（不下载、不改写）
            img.attrs = {'src': src, 'alt': alt}
            continue

        match = _DATA_URI_RE.match(src)
        if match is None:
            source = _short(src) if src else '缺少 src'
            warnings.append(f'第 {index} 张图片：来源无法读取（{source}），已移除')
            img.decompose()
            continue

        mime = (match.group('mime') or '').lower()
        ext = _MIME_TO_EXT.get(mime)
        if ext is None:
            warnings.append(f'第 {index} 张图片：不支持的图片类型（{mime or "未知"}），已移除')
            img.decompose()
            continue

        try:
            raw = base64.b64decode(match.group('payload'), validate=False)
        except (binascii.Error, ValueError):
            warnings.append(f'第 {index} 张图片：base64 数据损坏，已移除')
            img.decompose()
            continue

        try:
            processed = process_inline_image(raw, ext)
        except InlineImageError as exc:
            warnings.append(f'第 {index} 张图片：{exc}，已移除')
            img.decompose()
            continue

        rel = store_inline_image(processed.data)
        attrs = {'src': f'{settings.MEDIA_URL}{rel}', 'alt': alt}
        if title:
            attrs['title'] = title
        # bs4 的属性值类型是 ``str | AttributeValueList``，而 dict 不变，故此处收窄
        img.attrs = cast(dict[str, Any], attrs)
        stored += 1
    return stored


def _normalize(markdown: str) -> str:
    """收敛空白，并修掉便签类导出的两个坑。

    - ``&nbsp;`` 还原成空格、连续空行折叠、结尾保证单个换行；
    - **段落首行去前导空白**：便签导出常用若干空格做首行缩进，而 Markdown 里
      4 个前导空格等于**代码块**（实测整段被渲染成 ``<pre><code>``）；
    - **行尾保留硬换行**：markdownify 用 ``SPACES`` 风格把 ``<br>`` 转成行尾两个空格
      （Python-Markdown 不支持 CommonMark 的行尾反斜杠，用 ``BACKSLASH`` 会渲染出字面量
      ``\\``），所以这里只清多余空白、保留恰好两个空格的硬换行标记。

    代码块（````` ``` ````` / ``~~~`` 围栏）内的缩进与行尾空格原样保留。
    """
    text = markdown.replace('\xa0', ' ')
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out.append(line.rstrip())
            continue
        if in_fence:
            out.append(line)
            continue

        hard_break = line.endswith(_HARD_BREAK)
        stripped = line.rstrip()
        # 上一行为空即段落首行：去掉导出时留下的首行缩进
        if stripped and (not out or not out[-1].strip()):
            stripped = stripped.lstrip()
        if hard_break and stripped:
            stripped = f'{stripped}{_HARD_BREAK}'
        out.append(stripped)

    text = re.sub(r'\n{3,}', '\n\n', '\n'.join(out)).strip()
    return f'{text}\n' if text else ''


def html_to_markdown(raw_html: str) -> ConvertResult:
    """把 HTML 转成 Markdown 正文。

    :raises ConvertError: HTML 为空，或转换后提取不到任何正文内容。
    """
    if not (raw_html or '').strip():
        raise ConvertError('HTML 内容为空')

    soup = BeautifulSoup(raw_html, 'html.parser')
    for name in _DROP_TAGS:
        for tag in soup.find_all(name):
            tag.decompose()

    root = soup.body if soup.body is not None else soup
    _promote_divs(root)

    warnings: list[str] = []
    stored = _process_images(root, warnings)

    cleaned = nh3.clean(
        str(root),
        tags=_PRE_TAGS,
        attributes=_PRE_ATTRIBUTES,
        url_schemes=_PRE_URL_SCHEMES,
    )
    markdown = markdownify(
        cleaned,
        heading_style='ATX',
        bullets='-',
        # 必须是 SPACES：Python-Markdown 不支持 CommonMark 的行尾反斜杠硬换行，
        # 用 BACKSLASH 会把 ``\`` 当字面量渲染出来（实测）
        newline_style='SPACES',
        strip=['script', 'style'],
    )

    body = _normalize(markdown)
    if not body:
        # 图全被移除时正文可能为空：把首条告警带上，否则用户只看到「提取不到正文」
        # 而不知道是图片的问题
        detail = f'（{warnings[0]}）' if warnings else ''
        raise ConvertError(f'未能从该 HTML 中提取到正文内容{detail}')
    return ConvertResult(markdown=body, images=stored, warnings=warnings)
