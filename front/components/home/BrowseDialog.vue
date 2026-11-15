<script setup lang="ts">
/**
 * 浏览弹窗：搜索 / 分类 / 标签 三合一（对应导航三项）。
 *
 * 交互遵循 02-ux-spec §3：原生 `<dialog>` 拿焦点陷阱与 Esc；结果行整行可点，
 * 单一交互元素；关闭后焦点回触发按钮。数据走 /articles/search/、/articles/?category_slug=、
 * /articles/?tag_slug= 三条真实接口，不做本地过滤。
 *
 * 三个刻意的决定：
 * 1. 结果按 20 条一页、点「加载更多」追加，而不是一次拉一大页：弹窗是「快速定位」，
 *    首屏要快；想看全量的人有明确出口（页脚「查看全部」→ 带分页的独立页面）。
 * 2. 栏目/标签上的篇数走 /articles/stats/ 的聚合值，不再拉一页文章本地数——
 *    后者超过窗口上限会静默少算，芯片之和还会和「全部」对不上。
 * 3. 每次请求带序号，只认最后一次的回包：翻页和改关键词会并发，慢请求不能覆盖新结果。
 */
import type { Article, ArticleStats, Category, PaginatedResponse, Tag } from '~/types/api'

type BrowseMode = 'search' | 'category' | 'tag'

const PAGE_SIZE = 20

const props = withDefaults(
  defineProps<{
    /** 初始打开时的模式 */
    initialMode?: BrowseMode
  }>(),
  { initialMode: 'search' },
)

const open = defineModel<boolean>('open', { default: false })
const emit = defineEmits<{ (e: 'navigated'): void }>()

const dialogEl = ref<HTMLDialogElement | null>(null)
const inputEl = ref<HTMLInputElement | null>(null)

const mode = ref<BrowseMode>('search')
const keyword = ref('')
const activeCategory = ref('') // slug，'' = 全部
const activeTag = ref('') // slug，'' = 全部

const categories = ref<Category[]>([])
const tags = ref<Tag[]>([])
const stats = ref<ArticleStats | null>(null)

const results = ref<Article[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const loadingMore = ref(false)
const errorMsg = ref('')

/** 请求序号：翻页/改筛选并发时只认最后一次 */
let seq = 0

const MODE_LABEL: Record<BrowseMode, string> = { search: '搜索', category: '分类', tag: '标签' }

const hasMore = computed(() => results.value.length < total.value)

/** 芯片上的篇数来自聚合接口；取不到（接口失败）时退化成「只显示名称」，不给假数字 */
const categoryChips = computed(() =>
  categories.value.map(c => ({
    slug: c.slug,
    name: c.name,
    count: stats.value ? (stats.value.by_category[c.slug] ?? 0) : undefined,
  })),
)
const tagChips = computed(() =>
  tags.value.map(t => ({
    slug: t.slug,
    name: t.name,
    count: stats.value ? (stats.value.by_tag[t.slug] ?? 0) : undefined,
  })),
)
/** 「全部」用聚合 total（真值），拿不到才退回当前结果集的总数 */
const allCount = computed(() => stats.value?.total ?? total.value)

const showChips = computed(() => mode.value !== 'search')
const hintText = computed(() => {
  if (mode.value === 'category') return '按分类筛选已发布的游记'
  if (mode.value === 'tag') return '按标签筛选已发布的游记'
  return '在标题、摘要、正文里查找游记'
})

/** 页脚出口：去带完整分页的独立页面看全量 */
const exit = computed<{ to: string; label: string }>(() => {
  if (mode.value === 'search') {
    const word = keyword.value.trim()
    // 没输关键词时不该甩去「搜索页」（那页要求有关键词），改为按分类浏览
    return word
      ? { to: `/search?keyword=${encodeURIComponent(word)}`, label: '在搜索页查看全部' }
      : { to: '/categories', label: '按分类浏览' }
  }
  if (mode.value === 'category') {
    return activeCategory.value
      ? { to: `/category/${activeCategory.value}`, label: '查看该分类全部' }
      : { to: '/categories', label: '查看全部分类' }
  }
  return activeTag.value
    ? { to: `/tag/${activeTag.value}`, label: '查看该标签全部' }
    : { to: '/tags', label: '查看全部标签' }
})

function queryPath(): string {
  // 搜索接口要求 keyword 非空；空关键词时用普通列表（等于「全部游记」）
  return mode.value === 'search' && keyword.value.trim() ? '/articles/search/' : '/articles/'
}

function queryParams(target: number): Record<string, string | number> {
  const params: Record<string, string | number> = { page: target, page_size: PAGE_SIZE }
  if (mode.value === 'search') {
    const word = keyword.value.trim()
    if (word) params.keyword = word
  } else if (mode.value === 'category') {
    if (activeCategory.value) params.category_slug = activeCategory.value
  } else if (activeTag.value) {
    params.tag_slug = activeTag.value
  }
  return params
}

async function loadFirstPage() {
  const token = ++seq
  loading.value = true
  loadingMore.value = false
  errorMsg.value = ''
  try {
    const { data } = await useApi().get<PaginatedResponse<Article>>(
      queryPath(),
      queryParams(1),
    )
    if (token !== seq) return
    results.value = data.items
    total.value = data.total
    page.value = 1
  } catch (e) {
    if (token !== seq) return
    results.value = []
    total.value = 0
    errorMsg.value = errorMessage(e, '加载失败')
  } finally {
    if (token === seq) loading.value = false
  }
}

async function loadMore() {
  if (loading.value || loadingMore.value || !hasMore.value) return
  const token = seq
  loadingMore.value = true
  try {
    const next = page.value + 1
    const { data } = await useApi().get<PaginatedResponse<Article>>(
      queryPath(),
      queryParams(next),
    )
    if (token !== seq) return
    // 翻页期间可能有人刚发布文章，边界会重复；按 id 去重再追加
    const seen = new Set(results.value.map(item => item.id))
    results.value = [...results.value, ...data.items.filter(item => !seen.has(item.id))]
    total.value = data.total
    page.value = next
  } catch (e) {
    if (token !== seq) return
    errorMsg.value = errorMessage(e, '加载更多失败')
  } finally {
    if (token === seq) loadingMore.value = false
  }
}

async function ensureMeta() {
  if (categories.value.length && tags.value.length && stats.value) return
  try {
    const [catRes, tagRes, statsRes] = await Promise.all([
      useApi().get<Category[]>('/categories/'),
      useApi().get<Tag[]>('/tags/'),
      useApi().get<ArticleStats>('/articles/stats/'),
    ])
    categories.value = catRes.data
    tags.value = tagRes.data
    stats.value = statsRes.data
  } catch (e) {
    // 聚合失败不该让弹窗打不开：芯片退化成纯名称，列表照常
    errorMsg.value = errorMessage(e, '加载失败')
  }
}

function resetFor(next: BrowseMode) {
  mode.value = next
  keyword.value = ''
  activeCategory.value = ''
  activeTag.value = ''
}

function setMode(next: BrowseMode) {
  if (mode.value === next) return
  resetFor(next)
  void loadFirstPage()
}

function toggleCategory(slug: string) {
  activeCategory.value = activeCategory.value === slug ? '' : slug
  void loadFirstPage()
}

function toggleTag(slug: string) {
  activeTag.value = activeTag.value === slug ? '' : slug
  void loadFirstPage()
}

function go(slug: string) {
  open.value = false
  navigateTo(`/article/${slug}`)
  emit('navigated')
}

watch(open, async (v) => {
  const dlg = dialogEl.value
  if (v) {
    resetFor(props.initialMode)
    await ensureMeta()
    await loadFirstPage()
    await nextTick()
    // 原生 modal：拿焦点陷阱 / Esc / 背景 inert
    if (dlg && !dlg.open) dlg.showModal()
    if (mode.value === 'search') inputEl.value?.focus()
  } else if (dlg?.open) {
    dlg.close()
  }
})

watch(keyword, () => {
  if (mode.value !== 'search') return
  void loadFirstPage()
})
</script>

<template>
  <dialog
    ref="dialogEl"
    class="cv-bd"
    aria-labelledby="cv-bd-title"
    @cancel.prevent="open = false"
    @click.self="open = false"
  >
    <div class="cv-bd__box">
      <button type="button" class="cv-bd__close" aria-label="关闭" @click="open = false">
        <Icon name="lucide:x" class="h-5 w-5" />
      </button>

      <p class="cv-bd__eyebrow">浏览 / BROWSE</p>
      <h2 id="cv-bd-title">在游记中查找</h2>

      <div class="cv-bd__modes" role="group" aria-label="浏览方式">
        <button
          v-for="(label, key) in MODE_LABEL"
          :key="key"
          type="button"
          class="cv-bd__mode"
          :aria-pressed="mode === key"
          @click="setMode(key as BrowseMode)"
        >
          {{ label }}
        </button>
      </div>

      <div v-if="mode === 'search'" class="cv-bd__field">
        <span class="cv-bd__field-icon" aria-hidden="true">⌕</span>
        <input
          ref="inputEl"
          v-model="keyword"
          type="search"
          autocomplete="off"
          enterkeyhint="search"
          placeholder="输入标题、地点、日期…"
          aria-label="搜索游记"
        >
      </div>
      <p v-if="mode === 'search'" class="cv-bd__hint">{{ hintText }}</p>

      <div v-if="showChips" class="cv-bd__chips" role="group" aria-label="筛选">
        <button
          type="button"
          class="cv-bd__chip"
          :aria-pressed="(mode === 'category' ? !activeCategory : !activeTag)"
          @click="mode === 'category' ? toggleCategory('') : toggleTag('')"
        >
          全部 ({{ allCount }})
        </button>
        <template v-if="mode === 'category'">
          <button
            v-for="c in categoryChips"
            :key="c.slug"
            type="button"
            class="cv-bd__chip"
            :aria-pressed="activeCategory === c.slug"
            @click="toggleCategory(c.slug)"
          >
            {{ c.name }}<template v-if="c.count !== undefined"> ({{ c.count }})</template>
          </button>
        </template>
        <template v-else>
          <button
            v-for="t in tagChips"
            :key="t.slug"
            type="button"
            class="cv-bd__chip"
            :aria-pressed="activeTag === t.slug"
            @click="toggleTag(t.slug)"
          >
            #{{ t.name }}<template v-if="t.count !== undefined"> ({{ t.count }})</template>
          </button>
        </template>
      </div>

      <p v-if="showChips" class="cv-bd__hint">{{ hintText }}</p>

      <p class="cv-bd__count" role="status" aria-live="polite">
        {{ loading ? '加载中…' : `共 ${total} 篇` }}
      </p>

      <div class="cv-bd__results">
        <p v-if="errorMsg" class="cv-bd__error">{{ errorMsg }}</p>
        <p v-else-if="!loading && results.length === 0" class="cv-bd__empty">
          没有找到匹配的游记，试试「漠河」「黑龙江」这样的关键词。
        </p>
        <ul v-else role="list" class="cv-bd__list">
          <li v-for="(article, i) in results" :key="article.id" class="cv-bd__row">
            <button type="button" class="cv-bd__row-btn" @click="go(article.slug)">
              <img
                v-if="article.cover_image_url"
                :src="article.cover_image_url"
                alt=""
                width="40"
                height="28"
                loading="lazy"
              >
              <span v-else class="cv-bd__thumb-fallback" aria-hidden="true" />
              <span class="cv-bd__idx">{{ String(i + 1).padStart(2, '0') }}</span>
              <span class="cv-bd__title">{{ article.title }}</span>
              <span class="cv-bd__date">{{ formatDateCompact(article.publish_time) }}</span>
              <span v-if="article.category" class="cv-bd__cat">{{ article.category.name }}</span>
            </button>
          </li>
        </ul>

        <div v-if="!loading && !errorMsg && results.length" class="cv-bd__more">
          <button v-if="hasMore" type="button" class="cv-bd__more-btn" :disabled="loadingMore" @click="loadMore">
            {{ loadingMore ? '加载中…' : `加载更多（还有 ${total - results.length} 篇）` }}
          </button>
          <p v-else class="cv-bd__done">已显示全部 {{ total }} 篇</p>
        </div>
      </div>

      <div class="cv-bd__foot">
        <span>点标题在本页打开</span>
        <NuxtLink class="cv-bd__all" :to="exit.to" @click="open = false">
          {{ exit.label }} →
        </NuxtLink>
      </div>
    </div>
  </dialog>
</template>
