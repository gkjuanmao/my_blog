"""Markdown 渲染与消毒：**服务端唯一实现**。

固定管线（顺序不可调换）：

1. Python-Markdown 渲染（``fenced_code`` / ``tables`` / ``sane_lists``）；
2. treeprocessor 把表格的 ``style="text-align: x"`` 转成 ``align``（**必须在消毒前**，
   因为 nh3 会剥掉 ``style``）；
3. ``nh3.clean`` 白名单消毒 —— **这是唯一的安全边界**；
4. 消毒后用 ``html.parser`` **回填展示属性**（``img`` 懒加载、外链 ``target/rel``）。

为什么展示属性放在第 4 步而不是 treeprocessor：Python-Markdown 会把**原始 HTML**
stash 成占位符，``<img>``/``<a>`` 根本不在 ElementTree 里，treeprocessor 看不到它们
（实测：正文里手写 ``<img>`` 不会得到 ``loading="lazy"``）。在消毒后的最终 HTML 上回填
可同时覆盖 Markdown 语法与原始 HTML 两种来源。

事实说明（勿被误导）：
- Python-Markdown **没有** ``html:False`` 之类的开关，原始 HTML 默认**透传**，因此安全
  完全依赖第 3 步的 nh3 白名单，不得因为"渲染器已禁 HTML"而放松配置。
- 实测 nh3 0.3.x **保留相对路径**（``/media/inline/...``）与白名单内的属性，且会剥掉
  ``javascript:`` 等危险 URL，故无需"占位符两段式"兜底方案。
- ``markdown.Markdown.convert()`` 会改动实例内部状态，**非线程安全**；部署为 gthread
  多线程，因此这里**每次调用新建实例**，禁止模块级单例。
- ``html.parser.HTMLParser`` 必须 ``convert_charrefs=False``，否则会把 nh3 已转义的
  ``&lt;`` 解回 ``<``，等于**在消毒之后重新引入标签**。
"""
from html.parser import HTMLParser
from xml.etree.ElementTree import Element

import markdown
import nh3
from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor

# 允许保留的标签（白名单，其余一律剥除；标签内的文本会被保留）
ALLOWED_TAGS: set[str] = {
    'p', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'ul', 'ol', 'li', 'blockquote', 'pre', 'code',
    'a', 'img', 'strong', 'em', 'del', 'hr',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
}

# 允许保留的属性：只给必要标签开必要属性。
# 注意：img 的 loading/decoding 与 a 的 target/rel **不在此处** —— 它们在消毒之后由
# 我们注入（见 _DisplayAttrInjector），因此作者的原始 HTML 无法自带这些属性。
ALLOWED_ATTRIBUTES: dict[str, set[str]] = {
    'img': {'src', 'alt', 'title'},
    'a': {'href', 'title'},
    # fenced_code 会输出 <code class="language-xxx">
    'code': {'class'},
    'th': {'align'},
    'td': {'align'},
}

# 允许的 URL 协议（相对路径不受 url_schemes 限制，实测会原样保留）
URL_SCHEMES: set[str] = {'http', 'https', 'mailto'}

_EXTERNAL_PREFIXES = ('http://', 'https://')
_ALIGN_VALUES = {'left', 'center', 'right'}
_INJECT_TAGS = {'img', 'a'}


class _TableAlignTreeprocessor(Treeprocessor):
    """把表格单元格的 ``style="text-align: x"`` 转成 ``align``（nh3 会剥 style）。"""

    def run(self, root: Element) -> Element:  # noqa: D102 - 继承自 Treeprocessor
        for cell in list(root.iter('th')) + list(root.iter('td')):
            style = cell.attrib.pop('style', '')
            if 'text-align' in style:
                align = style.split('text-align:', 1)[1].split(';', 1)[0].strip()
                if align in _ALIGN_VALUES:
                    cell.set('align', align)
        return root


class _RenderAttrsExtension(Extension):
    """注册 ``_TableAlignTreeprocessor``（优先级 5：inline 之后、prettify 之前）。"""

    def extendMarkdown(self, md: markdown.Markdown) -> None:  # noqa: N802 - markdown API
        md.treeprocessors.register(_TableAlignTreeprocessor(md), 'table_align', 5)


def _escape_attr(value: str) -> str:
    """转义属性值（HTMLParser 已把实体解码，回写时必须重新转义）。"""
    return (
        value.replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
    )


def _build_tag(tag: str, attrs: list[tuple[str, str | None]], *, self_closing: bool) -> str:
    """重建起始标签（保留原属性顺序，追加注入的属性）。"""
    parts = [tag]
    for key, value in attrs:
        parts.append(key if value is None else f'{key}="{_escape_attr(value)}"')
    return f"<{' '.join(parts)}{' /' if self_closing else ''}>"


class _DisplayAttrInjector(HTMLParser):
    """在**已消毒**的 HTML 上回填展示属性（只追加，不改动现有属性值）。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []

    def _handle(self, tag: str, attrs: list[tuple[str, str | None]], *, self_closing: bool) -> None:
        if tag not in _INJECT_TAGS:
            # 未改动的标签原样回写，彻底避免转义往返差异
            original = self.get_starttag_text()
            if original is None:
                original = _build_tag(tag, attrs, self_closing=self_closing)
            self.parts.append(original)
            return
        attrs = list(attrs)
        names = {key for key, _ in attrs}
        if tag == 'img':
            if 'loading' not in names:
                attrs.append(('loading', 'lazy'))
            if 'decoding' not in names:
                attrs.append(('decoding', 'async'))
        elif tag == 'a':
            href = dict(attrs).get('href') or ''
            if href.startswith(_EXTERNAL_PREFIXES):
                if 'target' not in names:
                    attrs.append(('target', '_blank'))
                if 'rel' not in names:
                    attrs.append(('rel', 'noopener noreferrer'))
        self.parts.append(_build_tag(tag, attrs, self_closing=self_closing))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._handle(tag, attrs, self_closing=False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._handle(tag, attrs, self_closing=True)

    def handle_endtag(self, tag: str) -> None:
        self.parts.append(f'</{tag}>')

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        self.parts.append(f'&{name};')

    def handle_charref(self, name: str) -> None:
        self.parts.append(f'&#{name};')

    def handle_comment(self, data: str) -> None:
        self.parts.append(f'<!--{data}-->')

    def handle_decl(self, decl: str) -> None:
        self.parts.append(f'<!{decl}>')

    def handle_pi(self, data: str) -> None:
        self.parts.append(f'<?{data}>')

    def unknown_decl(self, data: str) -> None:
        self.parts.append(f'<![{data}]>')


def sanitize_html(raw_html: str) -> str:
    """对任意 HTML 片段做 nh3 白名单消毒（管线第 3 步，可单独复用）。"""
    return nh3.clean(
        raw_html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=URL_SCHEMES,
        link_rel=None,
    )


def inject_display_attributes(html: str) -> str:
    """回填展示属性（管线第 4 步）：``img`` 懒加载、外链 ``target/rel``。"""
    parser = _DisplayAttrInjector()
    parser.feed(html)
    parser.close()
    return ''.join(parser.parts)


def render_markdown(text: str | None) -> str:
    """把 Markdown 渲染成**已消毒并回填属性**的 HTML；空内容返回空串。"""
    if not text or not text.strip():
        return ''
    renderer = markdown.Markdown(
        extensions=['fenced_code', 'tables', 'sane_lists', _RenderAttrsExtension()]
    )
    return inject_display_attributes(sanitize_html(renderer.convert(text)))
