<script setup lang="ts">
/**
 * 浏览弹窗：搜索 / 分类 / 标签 三合一（对应导航三项）。
 *
 * 交互遵循 02-ux-spec §3：原生 `<dialog>` 拿焦点陷阱与 Esc；结果行整行可点，
 * 单一交互元素；关闭后焦点回触发按钮。数据走 /articles/search/、/articles/?category_slug=、
 * /articles/?tag_slug= 三条真实接口，不做本地过滤。
 */
import type { Article, Category, PaginatedResponse, Tag } from '~/types/api'

type BrowseMode = 'search' | 'category' | 'tag'

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
const results = ref<Article[]>([])
const total = ref(0)
const loading = ref(false)
const errorMsg = ref('')

/** 计数用的全量快照（最多 200 篇，足够本站规模） */
const allArticles = ref<Article[]>([])

const MODE_LABEL: Record<BrowseMode, string> = { search: '搜索', category: '分类', tag: '标签' }

const countMap = computed(() => {
  const byCategory = new Map<string, number>()
  const byTag = new Map<string, number>()
  for (const a of allArticles.value) {
    if (a.category) byCategory.set(a.category.slug, (byCategory.get(a.category.slug) ?? 0) + 1)
    for (const t of a.tags) byTag.set(t.slug, (byTag.get(t.slug) ?? 0) + 1)
  }
  return { byCategory, byTag }
})

const categoryChips = computed(() =>
  categories.value.map((c) => ({
    slug: c.slug,
    name: c.name,
    count: countMap.value.byCategory.get(c.slug) ?? 0,
  })),
)
const tagChips = computed(() =>
  tags.value.map((t) => ({
    slug: t.slug,
    name: t.name,
    count: countMap.value.byTag.get(t.slug) ?? 0,
  })),
)

const showChips = computed(() => mode.value !== 'search')
const hintText = computed(() => {
  if (mode.value === 'category') return '按分类筛选本页游记'
  if (mode.value === 'tag') return '按标签筛选本页游记'
  return '在标题、摘要、地点里查找游记'
})

async function fetchResults() {
  loading.value = true
  errorMsg.value = ''
  try {
    const params: Record<string, string | number> = { page: 1, page_size: 20 }
    if (mode.value === 'search') {
      if (!keyword.value.trim()) {
        results.value = allArticles.value.slice(0, 20)
        total.value = allArticles.value.length
        return
      }
      params.keyword = keyword.value.trim()
    } else if (mode.value === 'category') {
      if (activeCategory.value) params.category_slug = activeCategory.value
    } else if (activeTag.value) {
      params.tag_slug = activeTag.value
    }
    const path = mode.value === 'search' ? '/articles/search/' : '/articles/'
    const { data } = await useApi().get<PaginatedResponse<Article>>(path, params)
    results.value = data.items
    total.value = data.total
  } catch (e) {
    errorMsg.value = errorMessage(e, '加载失败')
  } finally {
    loading.value = false
  }
}

async function ensureMeta() {
  if (categories.value.length && tags.value.length && allArticles.value.length) return
  try {
    const [c, t, a] = await Promise.all([
      useApi().get<Category[]>('/categories/'),
      useApi().get<Tag[]>('/tags/'),
      useApi().get<PaginatedResponse<Article>>('/articles/', { page: 1, page_size: 100 }),
    ])
    categories.value = c.data
    tags.value = t.data
    allArticles.value = a.data.items
    total.value = a.data.total
  } catch (e) {
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
  void fetchResults()
}

function toggleCategory(slug: string) {
  activeCategory.value = activeCategory.value === slug ? '' : slug
  void fetchResults()
}

function toggleTag(slug: string) {
  activeTag.value = activeTag.value === slug ? '' : slug
  void fetchResults()
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
    await fetchResults()
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
  void fetchResults()
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
          全部 ({{ total || allArticles.length }})
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
            {{ c.name }} ({{ c.count }})
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
            #{{ t.name }} ({{ t.count }})
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
      </div>

      <p class="cv-bd__foot">
        共 {{ total }} 篇 · 点击标题在本页打开
      </p>
    </div>
  </dialog>
</template>
