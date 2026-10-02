"""HTML → Markdown 转换（后台「导入 HTML」）。

覆盖：垃圾标签清洗、空白规范化、段落提升、base64 内嵌图压缩与去重、外链/不可读来源处理、
往返保真（Markdown → 渲染 → 转回 Markdown），以及端点鉴权与大小限制。
"""
import base64
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from articles.convert import ConvertError, html_to_markdown
from articles.rendering import render_markdown
from articles.utils import suggest_title_from_filename

CONVERT_URL = '/api/v1/admin/articles/convert-html/'


def data_uri(jpeg_bytes: bytes, mime: str = 'image/jpeg') -> str:
    return f'data:{mime};base64,{base64.b64encode(jpeg_bytes).decode()}'


def inline_files() -> list[str]:
    from django.conf import settings

    directory = Path(settings.MEDIA_ROOT) / 'inline'
    return sorted(p.name for p in directory.iterdir()) if directory.is_dir() else []


class TestConvertCore:
    """转换器本体。"""

    def test_drops_script_and_style(self):
        """脚本与样式连同文本一起删除，不留关键字。"""
        result = html_to_markdown(
            '<html><head><style>p{color:red}</style></head>'
            '<body><script>alert(1)</script><p>正文</p></body></html>'
        )
        assert 'alert' not in result.markdown
        assert 'color:red' not in result.markdown
        assert '正文' in result.markdown

    def test_normalizes_nbsp_and_blank_lines(self):
        """``&nbsp;`` 还原成普通空格，连续空行折叠成一行。"""
        result = html_to_markdown('<p>a&nbsp;b</p><p></p><p></p><p>c</p>')
        assert '\xa0' not in result.markdown
        assert 'a b' in result.markdown
        assert '\n\n\n' not in result.markdown

    def test_promotes_inline_only_div_to_paragraph(self):
        """裸 div 当段落时不能把相邻两段黏成一行。"""
        result = html_to_markdown('<div>第一段</div><div>第二段</div>')
        assert '第一段' in result.markdown
        assert '第二段' in result.markdown
        assert '第一段第二段' not in result.markdown

    def test_keeps_block_child_inside_div(self):
        """含块级子元素的 div 不提升，避免非法嵌套。"""
        result = html_to_markdown('<div>前言<h2>小标题</h2></div>')
        assert '## 小标题' in result.markdown

    def test_headings_lists_bold_and_table(self):
        """标题用 ATX、列表、加粗与表格都要保结构。"""
        result = html_to_markdown(
            '<h2>行程</h2><ul><li>吃了<strong>火锅</strong></li></ul>'
            '<table><thead><tr><th>项目</th></tr></thead>'
            '<tbody><tr><td>住宿</td></tr></tbody></table>'
        )
        assert '## 行程' in result.markdown
        assert '**火锅**' in result.markdown
        assert '| 项目 |' in result.markdown
        assert '| 住宿 |' in result.markdown

    def test_empty_input_raises(self):
        """空 HTML 与无文字的 HTML 都报 ConvertError。"""
        with pytest.raises(ConvertError):
            html_to_markdown('')
        with pytest.raises(ConvertError):
            html_to_markdown('<html><body><p>  </p></body></html>')


class TestNoteAppQuirks:
    """便签类导出（div/span + 每行结尾 <br/> + 首行缩进）的回归。"""

    def test_br_becomes_hard_break_not_literal_backslash(self):
        """``<br>`` 必须转成行尾两空格（Python-Markdown 的有效语法），不能是反斜杠。

        回归：曾用 markdownify 的 ``BACKSLASH`` 风格，而 Python-Markdown 不支持
        CommonMark 的行尾反斜杠，结果**每行末尾都渲染出一个字面量 ``\\``**。
        """
        result = html_to_markdown('<p>第一行<br/>第二行</p>')

        assert '\\' not in result.markdown
        assert '第一行  \n第二行' in result.markdown
        assert '<br>' in render_markdown(result.markdown)

    def test_leading_indent_is_not_a_code_block(self):
        """导出时的首行缩进不能被 Markdown 当成代码块。

        回归：便签导出常给段落加 4 个空格缩进，而 4 个前导空格等于代码块，
        整段会被渲染成 ``<pre><code>``。
        """
        html = '<div><span>    正文一</span></div><div><span>    正文二</span></div>'
        result = html_to_markdown(html)

        assert '正文一' in result.markdown
        assert not any(line.startswith('    ') for line in result.markdown.splitlines())
        assert '<pre>' not in render_markdown(result.markdown)
        assert '正文二' in render_markdown(result.markdown)

    def test_fenced_code_keeps_inner_indent(self):
        """代码块内部的缩进必须原样保留（不能被"段落首行去缩进"误伤）。

        （行尾空格由 markdownify 自己归一化，不归 ``_normalize`` 管。）
        """
        result = html_to_markdown('<pre><code>line1\n    indented\n</code></pre>')

        assert '```' in result.markdown
        assert '    indented' in result.markdown


class TestConvertImages:
    """内联图处理。"""

    def test_base64_image_is_compressed_and_rewritten(self, jpeg_factory):
        """base64 图压成 WebP 落盘，正文里的 src 改写成站内 URL。"""
        img = f'<img src="{data_uri(jpeg_factory(size=(2400, 1800)))}" alt="山顶">'
        result = html_to_markdown(f'<p>{img}</p>')

        assert result.images == 1
        assert result.warnings == []
        assert result.markdown.count('/media/inline/') == 1
        assert '.webp' in result.markdown
        assert 'data:image' not in result.markdown
        assert '![山顶]' in result.markdown
        assert len(inline_files()) == 1

    def test_long_edge_is_downscaled(self, jpeg_factory):
        """最长边超过上限时会被缩小（省流量的核心）。"""
        from django.conf import settings
        from PIL import Image

        html_to_markdown(f'<img src="{data_uri(jpeg_factory(size=(3000, 1000)))}">')
        name = inline_files()[0]
        with Image.open(Path(settings.MEDIA_ROOT) / 'inline' / name) as image:
            assert max(image.size) <= settings.INLINE_IMAGE_MAX_LONG_EDGE

    def test_identical_images_stored_once(self, jpeg_factory):
        """同一张图出现两次：两处引用指向同一文件，磁盘只落一份。"""
        uri = data_uri(jpeg_factory())
        result = html_to_markdown(f'<img src="{uri}"><img src="{uri}">')

        assert result.images == 2
        assert result.markdown.count('/media/inline/') == 2
        assert len(set(inline_files())) == 1

    def test_external_image_kept(self):
        """外链图按约定保留原样（不下载、不改写）。"""
        result = html_to_markdown('<img src="https://example.com/a.jpg" alt="外链">')
        assert 'https://example.com/a.jpg' in result.markdown
        assert result.images == 0
        assert result.warnings == []

    def test_unreadable_source_removed_with_warning(self):
        """本地文件路径无法读取：移除并给出告警。"""
        result = html_to_markdown('<p>说明文字</p><img src="file:///sdcard/photo.jpg" alt="本地">')
        assert 'file:///sdcard' not in result.markdown
        assert '说明文字' in result.markdown
        assert len(result.warnings) == 1
        assert '无法读取' in result.warnings[0]

    def test_unsupported_mime_removed_with_warning(self):
        """GIF 不在支持列表内：移除并告警，不留 data URI。"""
        result = html_to_markdown(
            '<p>说明文字</p><img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=">'
        )
        assert 'data:image' not in result.markdown
        assert len(result.warnings) == 1
        assert '不支持' in result.warnings[0]

    def test_all_images_removed_reports_reason(self):
        """图全被移除导致正文为空时，错误信息要带上原因。"""
        with pytest.raises(ConvertError, match='无法读取'):
            html_to_markdown('<img src="file:///sdcard/photo.jpg">')


class TestRoundTrip:
    """往返保真：我们自己的渲染结果转回去不能丢结构。"""

    def test_markdown_survives_render_and_convert_back(self):
        source = (
            '# 游记标题\n\n'
            '正文有**加粗**与`代码`。\n\n'
            '## 第二天\n\n'
            '- 第一项\n- 第二项\n\n'
            '> 引用一句\n\n'
            '| 项目 | 花费 |\n| --- | --- |\n| 住宿 | 300 |\n'
        )
        result = html_to_markdown(render_markdown(source))
        markdown = result.markdown

        assert '# 游记标题' in markdown
        assert '## 第二天' in markdown
        assert '**加粗**' in markdown
        assert '- 第一项' in markdown
        assert '引用一句' in markdown
        assert '| 项目 | 花费 |' in markdown
        assert '| 住宿 | 300 |' in markdown


class TestConvertEndpoint:
    """端点：鉴权、输入通道与限制。"""

    def test_requires_staff(self, api_client, auth_header, staff_header, jpeg_factory):
        """普通用户被拒，staff 可用。"""
        payload = {'html': '<p>正文</p>'}
        assert api_client.post(CONVERT_URL, payload).status_code in (401, 403)
        assert api_client.post(CONVERT_URL, payload, **auth_header).status_code in (401, 403)

        response = api_client.post(CONVERT_URL, payload, **staff_header)
        assert response.status_code == 200

    def test_accepts_uploaded_file(self, api_client, staff_header, jpeg_factory):
        """multipart 文件通道可用（大 HTML 必须走这条，否则撞 2.5MB 请求体上限）。"""
        html = f'<div>第一段</div><p><img src="{data_uri(jpeg_factory())}"></p>'.encode()
        upload = SimpleUploadedFile('note.html', html, content_type='text/html')

        response = api_client.post(CONVERT_URL, {'file': upload}, **staff_header)
        assert response.status_code == 200

        data = response.json()['data']
        assert '第一段' in data['markdown']
        assert data['images'] == 1
        assert '/media/inline/' in data['markdown']
        assert data['warnings'] == []

    def test_accepts_pasted_html(self, api_client, staff_header):
        """粘贴文本通道可用，并回传告警。"""
        response = api_client.post(
            CONVERT_URL,
            {'html': '<h2>标题</h2><img src="file:///x/a.jpg">'},
            **staff_header,
        )
        assert response.status_code == 200

        data = response.json()['data']
        assert '## 标题' in data['markdown']
        assert data['images'] == 0
        assert len(data['warnings']) == 1

    def test_empty_payload_rejected(self, api_client, staff_header):
        """既没文件也没文本 → 400。"""
        response = api_client.post(CONVERT_URL, {'html': '   '}, **staff_header)
        assert response.status_code == 400
        assert '请选择 HTML 文件或粘贴' in response.json()['message']

    def test_content_without_text_rejected(self, api_client, staff_header):
        """只有标签没有文字 → 400（ConvertError 转成中文提示）。"""
        response = api_client.post(
            CONVERT_URL, {'html': '<html><body></body></html>'}, **staff_header
        )
        assert response.status_code == 400

    def test_size_limit_enforced(self, api_client, staff_header, settings):
        """超过 HTML_IMPORT_MAX_BYTES → 400。"""
        settings.HTML_IMPORT_MAX_BYTES = 64
        big = SimpleUploadedFile('big.html', b'<p>' + b'x' * 200 + b'</p>')

        response = api_client.post(CONVERT_URL, {'file': big}, **staff_header)
        assert response.status_code == 400
        assert '不能超过' in response.json()['message']

    def test_gbk_file_is_decoded(self, api_client, staff_header):
        """GBK 编码的导出文件（部分国产便签）也能转换。"""
        gbk = SimpleUploadedFile('gbk.html', '<div>中文正文</div>'.encode('gbk'))

        response = api_client.post(CONVERT_URL, {'file': gbk}, **staff_header)
        assert response.status_code == 200
        assert '中文正文' in response.json()['data']['markdown']

    def test_missing_file_object_is_not_required(self, api_client, staff_header, jpeg_factory):
        """不传 file 字段时不应因缺参数报 422。"""
        response = api_client.post(CONVERT_URL, {'html': '<p>a</p>'}, **staff_header)
        assert response.status_code != 422

    def test_large_html_goes_through_file_channel(self, api_client, staff_header, settings):
        """3MB 的 HTML 走**文件**通道能成功导入。

        这是本功能的关键假设：Django 的 ``DATA_UPLOAD_MAX_MEMORY_SIZE``（默认 2.5MB）
        只约束 ``request.body`` / 表单字段，**不含文件上传数据**。手机导出的 HTML 常因
        base64 内嵌图远超 2.5MB，若走 JSON 会被 RequestDataTooBig 直接拒掉。
        """
        assert settings.DATA_UPLOAD_MAX_MEMORY_SIZE is None or (
            settings.DATA_UPLOAD_MAX_MEMORY_SIZE < 3 * 1024 * 1024
        ), '前置条件：默认请求体上限应小于 3MB'
        body = ('<p>' + 'x' * 3_000_000 + '</p>').encode()
        upload = SimpleUploadedFile('big.html', body, content_type='text/html')

        response = api_client.post(CONVERT_URL, {'file': upload}, **staff_header)

        assert response.status_code == 200
        assert response.json()['data']['markdown'].startswith('x')


class TestSuggestedTitle:
    """便签导出的正文里没有标题，标题只在文件名里。"""

    @pytest.mark.parametrize(
        ('filename', 'expected'),
        [
            ('44 上海-罗马_202610030035_06899.html', '44 上海-罗马'),
            ('46 巴黎_202610040035.html', '46 巴黎'),
            ('我的游记 20261003.html', '我的游记'),
            ('note.html', 'note'),
            ('/tmp/dir/游记.html', '游记'),
            ('20261003.html', '20261003'),  # 整个文件名就是时间戳 → 回落原名
            ('第3章.html', '第3章'),  # 真实数字不能被误删
        ],
    )
    def test_infers_title_from_filename(self, filename, expected):
        assert suggest_title_from_filename(filename) == expected

    def test_endpoint_returns_suggestion_for_uploaded_file(self, api_client, staff_header):
        upload = SimpleUploadedFile(
            '44 上海-罗马_202610030035_06899.html', '<div>正文</div>'.encode()
        )

        response = api_client.post(CONVERT_URL, {'file': upload}, **staff_header)

        assert response.status_code == 200
        assert response.json()['data']['suggested_title'] == '44 上海-罗马'

    def test_endpoint_returns_empty_suggestion_for_paste(self, api_client, staff_header):
        """粘贴通道拿不到文件名，标题建议为空。"""
        response = api_client.post(CONVERT_URL, {'html': '<div>正文</div>'}, **staff_header)

        assert response.status_code == 200
        assert response.json()['data']['suggested_title'] == ''
