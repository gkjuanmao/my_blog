"""文章工具函数：slug 自动生成与唯一化。"""
import re
from typing import Any

from django.utils.text import slugify
from pypinyin import Style, lazy_pinyin

from .models import Article

# 便签类导出的常见命名：「标题_202610030035_06899.html」——尾部是时间戳与序号
_FILENAME_TIMESTAMP_RE = re.compile(r'[\s_\-]*\d{8}(?:[_\-]?\d{2,6})*(?:[_\-]\d+)?$')


def suggest_title_from_filename(filename: str) -> str:
    """从导出文件名推断标题：去掉目录、扩展名与尾部时间戳/序号。

    例：``44 上海-罗马_202610030035_06899.html`` → ``44 上海-罗马``。
    剥完为空（文件名本身就是时间戳）时，回落为去扩展名的原名。
    """
    stem = re.split(r'[/\\]', filename)[-1]
    if '.' in stem:
        stem = stem.rsplit('.', 1)[0]
    title = _FILENAME_TIMESTAMP_RE.sub('', stem).strip()
    return title or stem.strip()


def generate_slug(title: str) -> str:
    """由标题生成 URL 别名：中文转拼音，其余经 slugify 规范化。"""
    pinyin = '-'.join(lazy_pinyin(title, style=Style.NORMAL))
    slug = slugify(pinyin)
    return slug or 'article'


def unique_slug(slug: str, model: type[Any] = Article, exclude_id: int | None = None) -> str:
    """确保 slug 唯一：冲突时自动追加 -2、-3 等后缀。

    model 指定查询目标（Article/Category/Tag 等含 slug 字段的模型）；
    exclude_id 用于更新场景，排除自身避免误判冲突。
    """
    qs = model.objects.filter(slug=slug)
    if exclude_id is not None:
        qs = qs.exclude(pk=exclude_id)
    if not qs.exists():
        return slug

    base = slug
    index = 2
    while model.objects.filter(slug=f'{base}-{index}').exists():
        index += 1
    return f'{base}-{index}'
