"""计划器：匹配已有文章、决定动作、解析分类/标签（**预检与执行共用**）。

两阶段流程必须走同一个 planner，否则"预检看到的"与"实际执行的"会分叉。
本模块**只读**数据库，不写任何数据。
"""
from dataclasses import dataclass, field

from articles.models import Article, Category, Tag
from articles.utils import unique_slug

from .limits import Limits, limits
from .validate import ArticleEntry

STRATEGIES = ('skip', 'update', 'create_new')


@dataclass
class PlanItem:
    """单篇的既定动作。"""

    entry: ArticleEntry
    action: str  # create / update / skip / failed
    reason: str  # strategy / identical / invalid / action_override
    target_id: int | None = None
    final_slug: str | None = None
    replace_cover: bool = False
    replace_attachment: bool = False
    replace_images: bool = False
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        entry = self.entry
        return {
            'path': entry.dir_path or '.',
            'slug': entry.slug,
            'title': entry.title,
            'action': self.action,
            'effective_action': self.action,
            'skip_reason': self.reason if self.action == 'skip' else None,
            'target_id': self.target_id,
            'final_slug': self.final_slug or entry.slug,
            'warnings': self.warnings + entry.all_warnings(),
            'errors': self.errors + entry.errors,
        }


@dataclass
class Plan:
    """一次导入的完整计划。"""

    items: list[PlanItem]
    categories_to_create: list[dict] = field(default_factory=list)
    tags_to_create: list[dict] = field(default_factory=list)
    limits: Limits | None = None

    @property
    def has_overwrite(self) -> bool:
        """是否包含对既有记录的覆盖（决定是否生成回滚包）。

        注意：不能看"全局策略字符串"。决策 D9 允许单篇 ``import.action=update``
        覆盖全局的 ``skip``，只看全局策略会漏生成回滚包。
        """
        return any(item.action == 'update' for item in self.items)

    @property
    def touched_ids(self) -> list[int]:
        """会被改写的既有文章 id（回滚包只导出这些）。"""
        return sorted(
            item.target_id for item in self.items if item.action == 'update' and item.target_id
        )

    def totals(self) -> dict:
        counted = {'create': 0, 'update': 0, 'skip': 0, 'failed': 0}
        for item in self.items:
            counted[item.action] = counted.get(item.action, 0) + 1
        return {
            'total': len(self.items),
            **counted,
            'categories_to_create': [c['slug'] for c in self.categories_to_create],
            'tags_to_create': [t['slug'] for t in self.tags_to_create],
            'skipped_identical': sum(
                1 for item in self.items if item.action == 'skip' and item.reason == 'identical'
            ),
        }


def _effective_action(entry: ArticleEntry, global_strategy: str) -> tuple[str, str]:
    """包内 import.action 覆盖全局策略；非法值已在解析时回落为 auto。"""
    action = entry.parsed.import_action if entry.parsed else 'auto'
    if action == 'auto':
        return global_strategy, 'strategy'
    return action, 'action_override'


def _identical_article(entry: ArticleEntry) -> Article | None:
    """内容完全相同判定：slug + 封面/附件**存储字节**哈希（附件可缺省）+ 正文。

    - 附件可选后不能要求"附件哈希必须存在"，否则无附件文章永远判不出 identical，
      ``create_new`` 重试会无限复制。
    - DB 没有 content 哈希列，因此先按 slug 取候选，再在 Python 中比对正文；
      ``content`` 键不存在（v1 旧包）时不参与比对，避免破坏旧包幂等。
    """
    parsed = entry.parsed
    if parsed is None:
        return None
    if parsed.content.strip() == '' and entry.attachment is None and entry.cover is None:
        return None

    cover_sha = entry.cover.stored_sha256 if entry.cover is not None else ''
    attachment_sha = entry.attachment.stored_sha256 if entry.attachment is not None else ''
    candidates = Article.objects.filter(slug=parsed.slug).only(
        'id', 'slug', 'content', 'cover_image_sha256', 'file_sha256'
    )
    for article in candidates:
        if entry.cover is not None:
            if cover_sha != (article.cover_image_sha256 or ''):
                continue
        elif article.cover_image_sha256:
            continue
        if entry.attachment is not None:
            if attachment_sha != (article.file_sha256 or ''):
                continue
        elif article.file_sha256:
            continue
        if 'content' in parsed.present and article.content != parsed.content:
            continue
        return article
    return None


def _collect_taxonomy(
    items: list[PlanItem],
) -> tuple[list[dict], list[dict]]:
    """统计需要新建的分类/标签（只读数据库，不写入）。"""
    wanted_categories: dict[str, dict] = {}
    wanted_tags: dict[str, dict] = {}
    for item in items:
        if item.action not in ('create', 'update') or item.entry.parsed is None:
            continue
        parsed = item.entry.parsed
        if parsed.category:
            slug = str(parsed.category['slug'])
            wanted_categories.setdefault(
                slug,
                {
                    'slug': slug,
                    'name': str(parsed.category.get('name') or slug),
                    'description': str(parsed.category.get('description') or ''),
                },
            )
        for tag in parsed.tags or []:
            slug = str(tag['slug'])
            wanted_tags.setdefault(
                slug, {'slug': slug, 'name': str(tag.get('name') or slug)}
            )

    existing_categories = set(
        Category.objects.filter(slug__in=list(wanted_categories)).values_list('slug', flat=True)
    )
    existing_tags = set(
        Tag.objects.filter(slug__in=list(wanted_tags)).values_list('slug', flat=True)
    )
    to_create_categories = [v for k, v in wanted_categories.items() if k not in existing_categories]
    to_create_tags = [v for k, v in wanted_tags.items() if k not in existing_tags]
    return to_create_categories, to_create_tags


def build_plan(
    entries: list[ArticleEntry],
    *,
    strategy: str,
    user,
    lim: Limits | None = None,
) -> Plan:
    """产出计划：匹配、动作、媒体是否需要替换、taxonomy 需求。"""
    if strategy not in STRATEGIES:
        strategy = 'skip'
    cfg = lim or limits()
    items: list[PlanItem] = []

    for entry in entries:
        item = PlanItem(entry=entry, action='failed', reason='invalid')
        if not entry.ok() or entry.parsed is None:
            item.errors.extend(entry.errors or ['条目校验未通过'])
            items.append(item)
            continue

        action, reason = _effective_action(entry, strategy)
        existing = Article.objects.filter(slug=entry.parsed.slug).first()

        if action == 'create_new':
            identical = _identical_article(entry)
            if identical is not None:
                item.action, item.reason, item.target_id = 'skip', 'identical', identical.id
            else:
                item.action, item.reason = 'create', reason
                item.final_slug = unique_slug(entry.parsed.slug)
                item.replace_cover = True
                item.replace_attachment = True
                item.replace_images = bool(entry.images)
            items.append(item)
            continue

        if existing is None:
            item.action, item.reason = 'create', reason
            item.final_slug = unique_slug(entry.parsed.slug)
            item.replace_cover = True
            item.replace_attachment = True
            item.replace_images = bool(entry.images)
            items.append(item)
            continue

        item.target_id = existing.id
        item.final_slug = entry.parsed.slug
        if action == 'skip':
            item.action, item.reason = 'skip', reason
            items.append(item)
            continue

        # update：按**存储字节**哈希决定是否替换媒体（幂等键，见 D24）
        item.action = 'update'
        if entry.cover is not None:
            item.replace_cover = entry.cover.stored_sha256 != (existing.cover_image_sha256 or '')
        if entry.attachment is not None:
            item.replace_attachment = (
                entry.attachment.stored_sha256 != (existing.file_sha256 or '')
            )
        item.replace_images = bool(entry.images)
        items.append(item)

    # A5：导入同样要满足「正文与附件至少一项」，且按**最终状态**判断
    # （包内只改标题、目标文章本来就有正文/附件 → 合法；清空正文又没附件 → 失败）
    for item in items:
        if item.action not in ('create', 'update') or item.entry.parsed is None:
            continue
        parsed = item.entry.parsed
        existing = (
            Article.objects.filter(pk=item.target_id).only('content', 'file').first()
            if item.target_id
            else None
        )
        content = (
            parsed.content
            if 'content' in parsed.present
            else (existing.content if existing else '')
        )
        has_file = item.entry.attachment is not None or bool(existing and existing.file)
        if not content.strip() and not has_file:
            item.action, item.reason = 'failed', 'invalid'
            item.errors.append('导入后正文与附件皆为空，未满足「正文与附件至少填写一项」')

    categories_to_create, tags_to_create = _collect_taxonomy(items)
    if len(categories_to_create) > cfg.max_new_categories:
        for item in items:
            if item.action in ('create', 'update'):
                item.action, item.reason = 'failed', 'invalid'
                limit = cfg.max_new_categories
                item.errors.append(
                    f'本次将新建 {len(categories_to_create)} 个分类，超过上限 {limit}'
                )
        categories_to_create = []
    if len(tags_to_create) > cfg.max_new_tags:
        for item in items:
            if item.action in ('create', 'update'):
                item.action, item.reason = 'failed', 'invalid'
                item.errors.append(
                    f'本次将新建 {len(tags_to_create)} 个标签，超过上限 {cfg.max_new_tags}'
                )
        tags_to_create = []

    return Plan(
        items=items,
        categories_to_create=categories_to_create,
        tags_to_create=tags_to_create,
        limits=cfg,
    )
