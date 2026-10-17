<script setup lang="ts">
import type { CSSProperties } from 'vue'
import type { Article, Category, PaginatedResponse } from '~/types/api'

const articles = ref<Article[]>([])
const categories = ref<Category[]>([])
const total = ref(0)
const loading = ref(true)
const errorMsg = ref('')

const keywordInput = ref('')
const keyword = ref('')
const categorySlug = ref('')

const viewMode = ref<'stack' | 'list'>('stack')
/** 卡片堆栈的当前位置（始终为整数） */
const position = ref(0)

const failedCovers = reactive(new Set<number>())

const RAIL_MAX = 12

const monthDayFormatter = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  month: 'long',
  day: 'numeric',
})
const yearFormatter = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Shanghai',
  year: 'numeric',
})

function dateLabel(iso: string): string {
  return monthDayFormatter.format(new Date(iso))
}

function yearOf(iso: string): number {
  return Number(yearFormatter.format(new Date(iso)))
}

// 本页是独立画廊：仅在访问 /timeline 时把外壳刷成纯白，离开即自动移除
useHead({
  htmlAttrs: { class: 'tl-page' },
})

useSeoMeta({
  title: '时间轴',
  description: '沿着时间倒流，回看每一段旅程。',
})

try {
  const [articleRes, categoryRes] = await Promise.all([
    useApi().get<PaginatedResponse<Article>>('/articles/', { page: 1, page_size: 100 }),
    useApi().get<Category[]>('/categories/'),
  ])
  articles.value = articleRes.data.items
  total.value = articleRes.data.total
  categories.value = categoryRes.data
} catch (e) {
  errorMsg.value = errorMessage(e, '加载失败')
} finally {
  loading.value = false
}

/** 客户端筛选：标题/摘要/地点/标签/分类名，大小写不敏感 */
const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return articles.value.filter((article) => {
    if (categorySlug.value && article.category?.slug !== categorySlug.value) return false
    if (!kw) return true
    const haystack = [
      article.title,
      article.summary,
      article.location,
      article.category?.name ?? '',
      ...article.tags.map((tag) => tag.name),
    ]
      .join(' ')
      .toLowerCase()
    return haystack.includes(kw)
  })
})

const categoryOptions = computed(() =>
  categories.value.map((category) => ({
    slug: category.slug,
    name: category.name,
    count: articles.value.filter((article) => article.category?.slug === category.slug).length,
  })),
)

const stats = computed(() => {
  const years = articles.value.map((article) => yearOf(article.publish_time))
  return {
    count: total.value,
    categories: categoryOptions.value.length,
    span: years.length ? Math.max(...years) - Math.min(...years) + 1 : 0,
  }
})

const activeIndex = computed(() => {
  if (!filtered.value.length) return 0
  return Math.min(filtered.value.length - 1, Math.max(0, Math.round(position.value)))
})

const activeArticle = computed<Article | null>(() => filtered.value[activeIndex.value] ?? null)

const progress = computed(() => {
  const len = filtered.value.length
  if (!len) return 0
  if (len === 1) return 100
  return (activeIndex.value / (len - 1)) * 100
})

/** 只暴露当前视窗附近的卡片，避免一次性渲染上百个绝对定位层 */
const visibleCards = computed(() => {
  const pos = position.value
  return filtered.value
    .map((article, index) => ({ article, index, distance: index - pos }))
    .filter(({ distance }) => distance >= -1.6 && distance <= 3.4)
    .sort((a, b) => b.distance - a.distance)
})

/** 时间轴刻度：条目过多时均匀抽样，并始终保留当前项与每个年份的第一条 */
const railTicks = computed(() => {
  const len = filtered.value.length
  if (!len) return []

  const entries = filtered.value.map((article, index) => ({ article, index }))

  // 年份边界：跨年处的刻度额外展示年份
  const yearStarts = new Set<number>()
  let previousYear: number | null = null
  entries.forEach(({ article, index }) => {
    const year = yearOf(article.publish_time)
    if (year !== previousYear) {
      yearStarts.add(index)
      previousYear = year
    }
  })

  const decorate = (entry: { article: Article; index: number }) => ({
    ...entry,
    year: yearStarts.has(entry.index) ? yearOf(entry.article.publish_time) : null,
  })

  if (len <= RAIL_MAX) return entries.map(decorate)

  const stepSize = (len - 1) / (RAIL_MAX - 1)
  const selected = new Set<number>()
  for (let i = 0; i < RAIL_MAX; i += 1) selected.add(Math.round(i * stepSize))
  selected.add(activeIndex.value)
  yearStarts.forEach((index) => selected.add(index))

  return entries.filter(({ index }) => selected.has(index)).map(decorate)
})

function railTop(index: number): number {
  const len = filtered.value.length
  if (len <= 1) return 50
  return 4 + (index / (len - 1)) * 92
}

function clampPosition(value: number): number {
  const max = Math.max(0, filtered.value.length - 1)
  return Math.min(max, Math.max(0, value))
}

/** 滚轮累计达到该阈值就切换一张卡片（一格鼠标滚轮通常为 100） */
const WHEEL_STEP = 40

let wheelAccum = 0

function step(delta: number) {
  if (!filtered.value.length) return
  position.value = clampPosition(Math.round(position.value) + delta)
}

function jumpTo(index: number) {
  position.value = clampPosition(index)
}

function openActiveArticle() {
  if (!activeArticle.value) return
  navigateTo(`/article/${activeArticle.value.slug}`)
}

function selectCategory(slug: string) {
  categorySlug.value = slug
}

function submitSearch() {
  keyword.value = keywordInput.value.trim()
}

function resetFilters() {
  keywordInput.value = ''
  keyword.value = ''
  categorySlug.value = ''
}

function coverFailed(id: number) {
  failedCovers.add(id)
}

/** 滚轮驱动：同一方向的累计量达到一格就切换一张卡片；首尾处把滚动交还页面 */
function onWheel(event: WheelEvent) {
  if (viewMode.value !== 'stack' || event.ctrlKey) return
  if (Math.abs(event.deltaX) > Math.abs(event.deltaY)) return

  const current = Math.round(position.value)
  const direction = event.deltaY > 0 ? 1 : -1
  if (current + direction < 0 || current + direction > filtered.value.length - 1) {
    wheelAccum = 0
    return
  }

  event.preventDefault()

  if (Math.sign(wheelAccum) !== direction) wheelAccum = 0
  wheelAccum += event.deltaY

  if (Math.abs(wheelAccum) >= WHEEL_STEP) {
    wheelAccum = 0
    step(direction)
  }
}

function cardStyle(distance: number): CSSProperties {
  const translateZ = distance * -80
  const translateY = distance * -26
  const scale = Math.max(0.8, 1 - Math.abs(distance) * 0.03)
  return {
    transform: `translate(-50%, -50%) translate3d(0, ${translateY}px, ${translateZ}px) scale(${scale})`,
    opacity: distance < 0 ? Math.max(0, 1 + distance * 2) : 1,
    zIndex: Math.round((filtered.value.length - Math.abs(distance)) * 10),
    pointerEvents: Math.abs(distance) < 0.5 ? 'auto' : 'none',
    transition: 'transform 160ms ease-out, opacity 160ms ease-out',
  }
}

watch(filtered, () => {
  wheelAccum = 0
  position.value = 0
})
</script>

<template>
  <div class="tl-canvas">
    <!-- 流动背景：三团低饱和光斑缓慢漂移 -->
    <div class="tl-aurora" aria-hidden="true">
      <span class="tl-blob tl-blob--a" />
      <span class="tl-blob tl-blob--b" />
      <span class="tl-blob tl-blob--c" />
    </div>

    <div class="tl-shell">
      <header class="tl-head">
        <div class="tl-head-main">
          <p class="tl-eyebrow">
            <span>CHRONICLE</span>
            <span class="tl-eyebrow-sep" />
            <span>{{ stats.count }} STORIES</span>
          </p>
          <h1 class="tl-title">时间轴</h1>
          <p class="tl-sub">沿着时间倒流，回看每一段旅程。</p>
        </div>

        <dl class="tl-stats">
          <div class="tl-stat">
            <dt>篇游记</dt>
            <dd>{{ stats.count }}</dd>
          </div>
          <div class="tl-stat">
            <dt>个分类</dt>
            <dd>{{ stats.categories }}</dd>
          </div>
          <div class="tl-stat">
            <dt>年跨度</dt>
            <dd>{{ stats.span || '—' }}</dd>
          </div>
        </dl>
      </header>

      <form class="tl-search" role="search" @submit.prevent="submitSearch">
        <svg
          class="tl-search-icon"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.75"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
          focusable="false"
        >
          <circle cx="11" cy="11" r="8" />
          <path d="m21 21-4.3-4.3" />
        </svg>
        <input
          v-model="keywordInput"
          class="tl-search-input"
          type="search"
          placeholder="搜索标题、摘要、地点或标签"
          aria-label="搜索游记"
        >
        <button type="submit" class="tl-search-submit">搜索</button>
      </form>

      <div class="tl-filters">
        <span class="tl-filters-label">TYPE</span>
        <button
          type="button"
          class="tl-chip"
          :class="{ 'is-active': categorySlug === '' }"
          @click="selectCategory('')"
        >
          全部
          <span class="tl-chip-count">{{ articles.length }}</span>
        </button>
        <button
          v-for="option in categoryOptions"
          :key="option.slug"
          type="button"
          class="tl-chip"
          :class="{ 'is-active': categorySlug === option.slug }"
          @click="selectCategory(option.slug)"
        >
          {{ option.name }}
          <span class="tl-chip-count">{{ option.count }}</span>
        </button>
      </div>

      <div v-if="loading" class="tl-status">正在加载…</div>
      <div v-else-if="errorMsg" class="tl-status tl-status--error">{{ errorMsg }}</div>

      <section v-else class="tl-stage" aria-label="游记时间轴">
        <div class="tl-stage-head">
          <div class="tl-stage-caption">
            <p class="tl-stage-eyebrow">ON THIS DAY</p>
            <p class="tl-stage-date">
              {{ activeArticle ? formatDate(activeArticle.publish_time) : '暂无记录' }}
            </p>
          </div>

          <div class="tl-toggle" role="group" aria-label="切换视图">
            <button
              type="button"
              class="tl-toggle-btn"
              :class="{ 'is-active': viewMode === 'stack' }"
              aria-label="卡片视图"
              :aria-pressed="viewMode === 'stack'"
              @click="viewMode = 'stack'"
            >
              <svg
                class="tl-toggle-icon"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="1.75"
                stroke-linecap="round"
                stroke-linejoin="round"
                aria-hidden="true"
                focusable="false"
              >
                <path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z" />
                <path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65" />
                <path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65" />
              </svg>
            </button>
            <button
              type="button"
              class="tl-toggle-btn"
              :class="{ 'is-active': viewMode === 'list' }"
              aria-label="列表视图"
              :aria-pressed="viewMode === 'list'"
              @click="viewMode = 'list'"
            >
              <svg
                class="tl-toggle-icon"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="1.75"
                stroke-linecap="round"
                stroke-linejoin="round"
                aria-hidden="true"
                focusable="false"
              >
                <path d="M3 5h.01" />
                <path d="M3 12h.01" />
                <path d="M3 19h.01" />
                <path d="M8 5h13" />
                <path d="M8 12h13" />
                <path d="M8 19h13" />
              </svg>
            </button>
          </div>
        </div>

        <template v-if="filtered.length">
          <div v-if="viewMode === 'stack'">
            <div
              class="tl-stack"
              tabindex="0"
              aria-label="文章时间轴，使用上下方向键切换"
              @wheel="onWheel"
              @keydown.up.prevent="step(-1)"
              @keydown.left.prevent="step(-1)"
              @keydown.down.prevent="step(1)"
              @keydown.right.prevent="step(1)"
              @keydown.enter.prevent="openActiveArticle"
            >
              <div class="tl-stack-inner">
                <div
                  v-for="card in visibleCards"
                  :key="card.article.id"
                  class="tl-card-slot"
                  :style="cardStyle(card.distance)"
                >
                  <article
                    class="tl-card"
                    :class="{ 'is-active': Math.abs(card.distance) < 0.5 }"
                    @click="openActiveArticle"
                  >
                    <div class="tl-media">
                      <img
                        v-if="card.article.cover_image_url && !failedCovers.has(card.article.id)"
                        :src="card.article.cover_image_url"
                        :alt="card.article.title"
                        class="tl-media-img"
                        loading="lazy"
                        @error="coverFailed(card.article.id)"
                      >
                      <div v-else class="tl-media-fallback">
                        <svg
                          class="tl-media-fallback-icon"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          stroke-width="1.5"
                          stroke-linecap="round"
                          stroke-linejoin="round"
                          aria-hidden="true"
                          focusable="false"
                        >
                          <rect width="18" height="18" x="3" y="3" rx="2" ry="2" />
                          <circle cx="9" cy="9" r="2" />
                          <path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21" />
                        </svg>
                      </div>
                      <div
                        v-if="card.distance > 0"
                        class="tl-media-dim"
                        :style="{ opacity: Math.min(0.42, card.distance * 0.11) }"
                      />
                    </div>

                    <div class="tl-card-body">
                      <p class="tl-card-cat">
                        {{ yearOf(card.article.publish_time) }}
                        <span class="tl-card-cat-sep">/</span>
                        {{ card.article.category?.name || '游记' }}
                      </p>
                      <h2 class="tl-card-title">{{ card.article.title }}</h2>
                      <p class="tl-card-summary">{{ card.article.summary }}</p>
                      <div class="tl-card-meta">
                        <time>{{ formatDate(card.article.publish_time) }}</time>
                        <span class="tl-card-dot" />
                        <span>{{ card.article.views }} 次阅读</span>
                      </div>
                    </div>
                  </article>
                </div>
              </div>

              <!-- 右侧垂直时间轴 -->
              <div class="tl-rail">
                <button
                  v-for="tick in railTicks"
                  :key="tick.article.id"
                  type="button"
                  class="tl-rail-tick"
                  :class="{ 'is-active': activeIndex === tick.index }"
                  :style="{ top: `${railTop(tick.index)}%` }"
                  :aria-label="`跳转到 ${tick.article.title}`"
                  :aria-current="activeIndex === tick.index ? 'true' : undefined"
                  @click="jumpTo(tick.index)"
                >
                  <span class="tl-rail-label">
                    <span v-if="tick.year" class="tl-rail-year">{{ tick.year }}</span>
                    {{ dateLabel(tick.article.publish_time) }}
                  </span>
                  <span class="tl-rail-mark" />
                </button>
              </div>
            </div>

            <div class="tl-mobile">
              <button
                type="button"
                class="tl-mobile-btn"
                :disabled="activeIndex <= 0"
                aria-label="上一段"
                @click="step(-1)"
              >
                <svg
                  class="tl-mobile-icon"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.75"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  aria-hidden="true"
                  focusable="false"
                >
                  <path d="m12 19-7-7 7-7" />
                  <path d="M19 12H5" />
                </svg>
              </button>
              <div class="tl-mobile-center">
                <div class="tl-mobile-bar">
                  <span class="tl-mobile-bar-fill" :style="{ width: `${progress}%` }" />
                </div>
                <span class="tl-mobile-count">{{ activeIndex + 1 }} / {{ filtered.length }}</span>
              </div>
              <button
                type="button"
                class="tl-mobile-btn"
                :disabled="activeIndex >= filtered.length - 1"
                aria-label="下一段"
                @click="step(1)"
              >
                <svg
                  class="tl-mobile-icon"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.75"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  aria-hidden="true"
                  focusable="false"
                >
                  <path d="M5 12h14" />
                  <path d="m12 5 7 7-7 7" />
                </svg>
              </button>
            </div>

            <p class="tl-hint">滚轮或 ↑ ↓ 切换 · 点击卡片阅读 · 点击右侧时间轴跳转</p>
          </div>

          <!-- 列表视图 -->
          <div v-else class="tl-list">
            <NuxtLink
              v-for="article in filtered"
              :key="article.id"
              :to="`/article/${article.slug}`"
              class="tl-list-row"
            >
              <time class="tl-list-date">{{ formatDate(article.publish_time) }}</time>
              <div class="tl-list-thumb">
                <img
                  v-if="article.cover_image_url && !failedCovers.has(article.id)"
                  :src="article.cover_image_url"
                  :alt="article.title"
                  class="tl-list-thumb-img"
                  loading="lazy"
                  @error="coverFailed(article.id)"
                >
                <div v-else class="tl-list-thumb-fallback">
                  <svg
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.5"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    aria-hidden="true"
                    focusable="false"
                  >
                    <rect width="18" height="18" x="3" y="3" rx="2" ry="2" />
                    <circle cx="9" cy="9" r="2" />
                    <path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21" />
                  </svg>
                </div>
              </div>
              <div class="tl-list-main">
                <p class="tl-list-cat">
                  {{ yearOf(article.publish_time) }}
                  <span class="tl-card-cat-sep">/</span>
                  {{ article.category?.name || '游记' }}
                </p>
                <h3 class="tl-list-title">{{ article.title }}</h3>
                <p class="tl-list-summary">{{ article.summary }}</p>
              </div>
              <svg
                class="tl-list-arrow"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="1.75"
                stroke-linecap="round"
                stroke-linejoin="round"
                aria-hidden="true"
                focusable="false"
              >
                <path d="M7 7h10v10" />
                <path d="M7 17 17 7" />
              </svg>
            </NuxtLink>
          </div>
        </template>

        <div v-else class="tl-empty">
          <svg
            class="tl-empty-icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
            focusable="false"
          >
            <circle cx="12" cy="12" r="10" />
            <path d="m16.24 7.76-1.804 5.411a2 2 0 0 1-1.265 1.265L7.76 16.24l1.804-5.411a2 2 0 0 1 1.265-1.265z" />
          </svg>
          <p class="tl-empty-text">没有符合条件的记录</p>
          <button type="button" class="tl-search-submit" @click="resetFilters">清除筛选</button>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
/* ---------- 画布与流动背景 ---------- */
.tl-canvas {
  position: relative;
  isolation: isolate;
  overflow: hidden;
  min-height: calc(100vh - 140px);
  color: #111111;
  font-family:
    ui-sans-serif,
    system-ui,
    -apple-system,
    'Segoe UI',
    'PingFang SC',
    'Hiragino Sans GB',
    'Microsoft YaHei',
    sans-serif;
}

.tl-canvas svg {
  display: block;
  flex: none;
}

.tl-aurora {
  position: absolute;
  inset: 0;
  z-index: -1;
  overflow: hidden;
  pointer-events: none;
}

.tl-blob {
  position: absolute;
  display: block;
  border-radius: 50%;
  filter: blur(90px);
  will-change: transform;
}

.tl-blob--a {
  top: -160px;
  left: -140px;
  width: min(58vw, 660px);
  height: min(58vw, 660px);
  background: radial-gradient(circle at 35% 35%, rgba(255, 177, 102, 0.55), rgba(255, 177, 102, 0) 70%);
  opacity: 0.7;
  animation: tl-drift-a 26s ease-in-out infinite alternate;
}

.tl-blob--b {
  top: 26%;
  right: -200px;
  width: min(62vw, 720px);
  height: min(62vw, 720px);
  background: radial-gradient(circle at 50% 50%, rgba(116, 176, 196, 0.5), rgba(116, 176, 196, 0) 70%);
  opacity: 0.62;
  animation: tl-drift-b 32s ease-in-out infinite alternate;
}

.tl-blob--c {
  bottom: -220px;
  left: 18%;
  width: min(54vw, 620px);
  height: min(54vw, 620px);
  background: radial-gradient(circle at 50% 50%, rgba(196, 158, 214, 0.46), rgba(196, 158, 214, 0) 70%);
  opacity: 0.55;
  animation: tl-drift-c 29s ease-in-out infinite alternate;
}

@keyframes tl-drift-a {
  0% {
    transform: translate3d(0, 0, 0) scale(1);
  }
  50% {
    transform: translate3d(6vw, 7vh, 0) scale(1.1);
  }
  100% {
    transform: translate3d(-3vw, 13vh, 0) scale(0.96);
  }
}

@keyframes tl-drift-b {
  0% {
    transform: translate3d(0, 0, 0) scale(1);
  }
  50% {
    transform: translate3d(-7vw, -8vh, 0) scale(0.92);
  }
  100% {
    transform: translate3d(3vw, 6vh, 0) scale(1.08);
  }
}

@keyframes tl-drift-c {
  0% {
    transform: translate3d(0, 0, 0) scale(1);
  }
  50% {
    transform: translate3d(5vw, -6vh, 0) scale(1.12);
  }
  100% {
    transform: translate3d(-6vw, 4vh, 0) scale(0.94);
  }
}

@media (prefers-reduced-motion: reduce) {
  .tl-blob {
    animation: none;
  }
}

/* ---------- 版心 ---------- */
.tl-shell {
  max-width: 1120px;
  margin: 0 auto;
  padding: 36px 28px 72px;
}

/* ---------- 头部 ---------- */
.tl-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 36px;
}

.tl-eyebrow {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 0;
  font-size: 11px;
  letter-spacing: 0.32em;
  text-transform: uppercase;
  color: #a3a3a0;
}

.tl-eyebrow-sep {
  width: 24px;
  height: 1px;
  background: #d8d8d4;
}

.tl-title {
  margin: 10px 0 0;
  font-size: clamp(38px, 5.4vw, 64px);
  font-weight: 900;
  line-height: 0.96;
  letter-spacing: -0.035em;
  color: #0a0a0a;
}

.tl-sub {
  margin: 12px 0 0;
  font-size: 14px;
  line-height: 1.6;
  color: #737373;
}

.tl-stats {
  display: flex;
  gap: 36px;
  margin: 0;
  padding-bottom: 4px;
}

.tl-stat {
  display: flex;
  flex-direction: column-reverse;
  gap: 8px;
}

.tl-stat dd {
  margin: 0;
  font-size: 28px;
  font-weight: 800;
  line-height: 1;
  letter-spacing: -0.04em;
  color: #0a0a0a;
  font-variant-numeric: tabular-nums;
}

.tl-stat dt {
  font-size: 10px;
  letter-spacing: 0.24em;
  text-transform: uppercase;
  color: #a8a8a4;
}

/* ---------- 搜索 ---------- */
.tl-search {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 26px;
  padding-bottom: 12px;
  border-bottom: 1px solid #e7e7e3;
  transition: border-color 0.25s ease;
}

.tl-search:focus-within {
  border-color: #0a0a0a;
}

.tl-search-icon {
  flex: none;
  width: 20px;
  height: 20px;
  color: #a8a8a4;
}

.tl-search-input {
  flex: 1;
  min-width: 0;
  padding: 6px 0;
  border: 0;
  background: transparent;
  outline: none;
  appearance: none;
  font-family: inherit;
  font-size: 16px;
  color: #0a0a0a;
}

.tl-search-input::-webkit-search-cancel-button {
  appearance: none;
}

.tl-search-input::placeholder {
  color: #b8b8b4;
}

.tl-search-submit {
  flex: none;
  padding: 9px 20px;
  border: 0;
  border-radius: 999px;
  background: #0a0a0a;
  font-family: inherit;
  font-size: 13px;
  letter-spacing: 0.08em;
  color: #ffffff;
  cursor: pointer;
  transition:
    background 0.2s ease,
    transform 0.2s ease;
}

.tl-search-submit:hover {
  background: #262626;
  transform: translateY(-1px);
}

/* ---------- 类型筛选 ---------- */
.tl-filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 16px;
}

.tl-filters-label {
  margin-right: 8px;
  font-size: 10px;
  letter-spacing: 0.28em;
  text-transform: uppercase;
  color: #b4b4b0;
}

.tl-chip {
  padding: 8px 15px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  font-family: inherit;
  font-size: 13px;
  color: #70706c;
  cursor: pointer;
  transition:
    background 0.2s ease,
    color 0.2s ease;
}

.tl-chip:hover {
  background: #f2f2ef;
  color: #0a0a0a;
}

.tl-chip.is-active {
  background: #0a0a0a;
  color: #ffffff;
}

.tl-chip-count {
  margin-left: 6px;
  font-size: 11px;
  opacity: 0.55;
}

/* ---------- 状态 ---------- */
.tl-status {
  padding: 120px 0;
  text-align: center;
  font-size: 13px;
  letter-spacing: 0.2em;
  color: #a8a8a4;
}

.tl-status--error {
  color: #b42318;
}

/* ---------- 舞台 ---------- */
.tl-stage {
  margin-top: 28px;
}

.tl-stage-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
}

.tl-stage-eyebrow {
  margin: 0;
  font-size: 10px;
  letter-spacing: 0.3em;
  text-transform: uppercase;
  color: #b0b0ac;
}

.tl-stage-date {
  margin: 4px 0 0;
  font-size: 13px;
  letter-spacing: 0.04em;
  color: #4a4a46;
}

.tl-toggle {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 999px;
  background: #f3f3f0;
}

.tl-toggle-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: #8a8a86;
  cursor: pointer;
  transition:
    background 0.2s ease,
    color 0.2s ease;
}

.tl-toggle-btn:hover {
  color: #0a0a0a;
}

.tl-toggle-btn.is-active {
  background: #0a0a0a;
  color: #ffffff;
}

.tl-toggle-icon {
  width: 16px;
  height: 16px;
}

/* ---------- 3D 卡片堆栈 ---------- */
.tl-stack {
  position: relative;
  height: 480px;
  margin-top: 24px;
  overflow: hidden;
  perspective: 1600px;
  outline: none;
}

.tl-stack:focus-visible {
  outline: 2px solid #0a0a0a;
  outline-offset: 6px;
  border-radius: 32px;
}

.tl-stack-inner {
  position: absolute;
  inset: 0;
  transform-style: preserve-3d;
}

.tl-card-slot {
  position: absolute;
  left: calc(50% - 80px);
  top: 50%;
  width: min(860px, calc(100% - 220px));
}

.tl-card {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #ffffff;
  border-radius: 28px;
  box-shadow: 0 40px 90px -48px rgba(10, 10, 10, 0.42);
  cursor: default;
}

.tl-card.is-active {
  cursor: pointer;
}

.tl-media {
  position: relative;
  height: 340px;
  overflow: hidden;
  background: #f1f1ee;
}

.tl-media-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.6s cubic-bezier(0.19, 1, 0.22, 1);
}

.tl-card.is-active:hover .tl-media-img {
  transform: scale(1.04);
}

.tl-media-fallback {
  display: flex;
  width: 100%;
  height: 100%;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #f6f3ee, #ecebe7);
}

.tl-media-fallback-icon {
  width: 36px;
  height: 36px;
  color: #c2c2bd;
}

.tl-media-dim {
  position: absolute;
  inset: 0;
  background: #0a0a0a;
  transition: opacity 0.2s ease;
}

.tl-card-body {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 34px 38px 34px 36px;
  background: #ffffff;
}

.tl-card-cat {
  margin: 0;
  font-size: 10px;
  letter-spacing: 0.26em;
  text-transform: uppercase;
  color: #a0a09c;
}

.tl-card-cat-sep {
  margin: 0 4px;
  color: #d0d0cb;
}

.tl-card-title {
  display: -webkit-box;
  margin: 14px 0 0;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  font-size: 26px;
  font-weight: 800;
  line-height: 1.26;
  letter-spacing: -0.02em;
  color: #0a0a0a;
}

.tl-card-summary {
  display: -webkit-box;
  margin: 14px 0 0;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  font-size: 15px;
  line-height: 1.72;
  color: #737373;
}

.tl-card-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 26px;
  font-size: 12px;
  letter-spacing: 0.04em;
  color: #9c9c98;
  font-variant-numeric: tabular-nums;
}

.tl-card-dot {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: #cecec9;
}

/* ---------- 右侧时间轴 ---------- */
.tl-rail {
  position: absolute;
  top: 40px;
  right: 0;
  bottom: 40px;
  display: none;
  width: 168px;
}

.tl-rail-year {
  margin-right: 6px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.14em;
  color: #0a0a0a;
  font-variant-numeric: tabular-nums;
}

.tl-rail-tick {
  position: absolute;
  right: 0;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 10px 0;
  border: 0;
  background: transparent;
  transform: translateY(-50%);
  cursor: pointer;
}

.tl-rail-label {
  font-size: 13px;
  letter-spacing: 0.06em;
  white-space: nowrap;
  color: #b4b4af;
  opacity: 0.5;
  font-variant-numeric: tabular-nums;
  transition:
    opacity 0.2s ease,
    color 0.2s ease;
}

.tl-rail-tick:hover .tl-rail-label {
  opacity: 1;
  color: #4d4d48;
}

.tl-rail-tick.is-active .tl-rail-label {
  opacity: 1;
  font-weight: 600;
  color: #0a0a0a;
}

.tl-rail-mark {
  width: 14px;
  height: 2px;
  border-radius: 2px;
  background: #deded9;
  transition:
    width 0.25s ease,
    background 0.25s ease;
}

.tl-rail-tick:hover .tl-rail-mark {
  width: 22px;
  background: #a3a39e;
}

.tl-rail-tick.is-active .tl-rail-mark {
  width: 34px;
  background: #0a0a0a;
}

/* ---------- 移动端控制 ---------- */
.tl-mobile {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-top: 20px;
}

.tl-mobile-btn {
  display: flex;
  flex: none;
  width: 44px;
  height: 44px;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 50%;
  background: #0a0a0a;
  color: #ffffff;
  cursor: pointer;
  transition: opacity 0.2s ease;
}

.tl-mobile-btn:disabled {
  opacity: 0.22;
  cursor: default;
}

.tl-mobile-icon {
  width: 16px;
  height: 16px;
}

.tl-mobile-center {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.tl-mobile-bar {
  width: 100%;
  height: 2px;
  overflow: hidden;
  border-radius: 999px;
  background: #ecece8;
}

.tl-mobile-bar-fill {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: #0a0a0a;
  transition: width 0.25s ease;
}

.tl-mobile-count {
  font-size: 10px;
  letter-spacing: 0.16em;
  color: #a8a8a4;
  font-variant-numeric: tabular-nums;
}

.tl-hint {
  display: none;
  margin: 26px 0 0;
  text-align: center;
  font-size: 11px;
  letter-spacing: 0.16em;
  color: #b4b4b0;
}

/* ---------- 列表视图 ---------- */
.tl-list {
  max-height: clamp(320px, calc(100vh - 445px), 680px);
  margin-top: 18px;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: #d8d8d3 transparent;
}

.tl-list-row {
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 14px 12px;
  border-bottom: 1px solid #f0f0ec;
  border-radius: 18px;
  text-decoration: none;
  transition: background 0.2s ease;
}

.tl-list-row:hover {
  background: #fafaf7;
}

.tl-list-date {
  flex: none;
  width: 112px;
  font-size: 12px;
  letter-spacing: 0.04em;
  color: #a0a09c;
  font-variant-numeric: tabular-nums;
}

.tl-list-thumb {
  flex: none;
  width: 96px;
  height: 66px;
  overflow: hidden;
  border-radius: 12px;
  background: #f1f1ee;
}

.tl-list-thumb-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.45s cubic-bezier(0.19, 1, 0.22, 1);
}

.tl-list-row:hover .tl-list-thumb-img {
  transform: scale(1.06);
}

.tl-list-thumb-fallback {
  display: flex;
  width: 100%;
  height: 100%;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #f6f3ee, #ecebe7);
  color: #c2c2bd;
}

.tl-list-thumb-fallback svg {
  width: 22px;
  height: 22px;
}

.tl-list-main {
  min-width: 0;
  flex: 1;
}

.tl-list-cat {
  margin: 0;
  font-size: 10px;
  letter-spacing: 0.26em;
  text-transform: uppercase;
  color: #a8a8a4;
}

.tl-list-title {
  margin: 8px 0 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 19px;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: #0a0a0a;
}

.tl-list-summary {
  margin: 8px 0 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  line-height: 1.6;
  color: #8a8a86;
}

.tl-list-arrow {
  flex: none;
  width: 18px;
  height: 18px;
  margin-top: 4px;
  color: #c4c4bf;
  transition:
    transform 0.2s ease,
    color 0.2s ease;
}

.tl-list-row:hover .tl-list-arrow {
  color: #0a0a0a;
  transform: translate(2px, -2px);
}

/* ---------- 空态 ---------- */
.tl-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 120px 0;
  text-align: center;
}

.tl-empty-icon {
  width: 32px;
  height: 32px;
  color: #c8c8c3;
}

.tl-empty-text {
  margin: 18px 0 22px;
  font-size: 14px;
  color: #8a8a86;
}

/* ---------- 响应式 ---------- */
@media (min-width: 640px) {
  .tl-rail {
    display: block;
  }

  .tl-mobile {
    display: none;
  }

  .tl-hint {
    display: block;
  }

  .tl-stack {
    height: 560px;
  }

  .tl-card-slot {
    left: calc(50% - 70px);
    width: min(480px, calc(100% - 200px));
  }

  .tl-media {
    height: 260px;
  }

  .tl-card-body {
    padding: 26px 30px;
  }

  .tl-card-title {
    font-size: 22px;
  }
}

@media (min-width: 900px) {
  .tl-stack {
    height: 480px;
  }

  .tl-card-slot {
    left: calc(50% - 80px);
    width: min(860px, calc(100% - 220px));
  }

  .tl-card {
    display: grid;
    grid-template-columns: minmax(0, 1.32fr) minmax(0, 1fr);
  }

  .tl-media {
    height: 340px;
  }

  .tl-card-body {
    padding: 34px 38px 34px 36px;
  }

  .tl-card-title {
    font-size: 26px;
  }
}

@media (max-width: 639px) {
  .tl-shell {
    padding: 28px 20px 56px;
  }

  .tl-head {
    gap: 28px;
  }

  .tl-stats {
    gap: 32px;
  }

  .tl-stat dd {
    font-size: 30px;
  }

  .tl-search {
    margin-top: 36px;
  }

  .tl-search-input {
    font-size: 16px;
  }

  .tl-stage {
    margin-top: 20px;
  }

  .tl-stack {
    height: 460px;
    margin-top: 20px;
  }

  .tl-card-slot {
    left: 50%;
    width: min(320px, calc(100% - 8px));
  }

  .tl-media {
    height: 220px;
  }

  .tl-card-title {
    font-size: 19px;
  }

  .tl-card-body {
    padding: 16px 18px 18px;
  }

  .tl-card-summary {
    -webkit-line-clamp: 2;
  }

  .tl-card-meta {
    margin-top: 18px;
  }

  .tl-list-row {
    gap: 12px;
    padding: 12px 2px;
  }

  .tl-list-date {
    display: none;
  }

  .tl-list-thumb {
    width: 68px;
    height: 48px;
    border-radius: 10px;
  }

  .tl-list-title {
    white-space: normal;
  }

  .tl-list-summary {
    white-space: normal;
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
  }
}

/* ---------- 键盘可见焦点 ---------- */
.tl-search-submit:focus-visible,
.tl-chip:focus-visible,
.tl-toggle-btn:focus-visible,
.tl-mobile-btn:focus-visible,
.tl-rail-tick:focus-visible {
  outline: 2px solid #0a0a0a;
  outline-offset: 3px;
}
</style>

<!-- 只在 /timeline 挂载期间生效：把公共外壳刷成纯白，离开时 html 类被移除 -->
<style>
html.tl-page,
html.tl-page body {
  background-color: #ffffff;
}

html.tl-page .public-shell {
  background-color: #ffffff !important;
  background-image: none !important;
}

html.tl-page .public-shell::after {
  display: none !important;
}

html.tl-page main {
  max-width: none !important;
  padding: 0 !important;
}
</style>
