"""默认分类/标签：确保每个新建文章都有分类与标签。"""
from .models import Category, Tag

DEFAULT_CATEGORY_SLUG = 'default-category'
DEFAULT_TAG_SLUG = 'default-tag'


def ensure_defaults() -> tuple[Category, Tag]:
    """幂等：不存在则创建默认分类/标签，返回二者。"""
    category, _ = Category.objects.get_or_create(
        slug=DEFAULT_CATEGORY_SLUG,
        defaults={'name': '默认分类', 'description': '系统默认分类'},
    )
    tag, _ = Tag.objects.get_or_create(
        slug=DEFAULT_TAG_SLUG,
        defaults={'name': '默认标签'},
    )
    return category, tag
