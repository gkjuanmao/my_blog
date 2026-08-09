"""文章工具函数：slug 自动生成与唯一化。"""
from django.utils.text import slugify
from pypinyin import Style, lazy_pinyin

from .models import Article


def generate_slug(title: str) -> str:
    """由标题生成 URL 别名：中文转拼音，其余经 slugify 规范化。"""
    pinyin = '-'.join(lazy_pinyin(title, style=Style.NORMAL))
    slug = slugify(pinyin)
    return slug or 'article'


def unique_slug(slug: str, exclude_id: int | None = None) -> str:
    """确保 slug 唯一：冲突时自动追加 -2、-3 等后缀。

    exclude_id 用于更新场景，排除自身避免误判冲突。
    """
    qs = Article.objects.filter(slug=slug)
    if exclude_id is not None:
        qs = qs.exclude(pk=exclude_id)
    if not qs.exists():
        return slug

    base = slug
    index = 2
    while Article.objects.filter(slug=f'{base}-{index}').exists():
        index += 1
    return f'{base}-{index}'
