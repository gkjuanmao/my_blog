<script setup lang="ts">
/**
 * 时间轴：按年分组倒序浏览全部游记，样式与首页同源（--hp-* 令牌）。
 * 数据仍走 /articles/ 与 /categories/，筛选在客户端做（规模小，一页 200 篇够用）。
 */
import type { Article, Category, PaginatedResponse } from '~/types/api'

const articles = ref<Article[]>([])
const categories = ref<Category[]>([])
const total = ref(0)
const loading = ref(true)
const errorMsg = ref('')

const keyword = ref('')
const categorySlug = ref('')

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

const yearFormatter = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric' })
const monthDayFormatter = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  month: '2-digit',
  day: '2-digit',
})

function yearOf(iso: string): number {
  return Number(yearFormatter.format(new Date(iso)))
}

function dayLabel(iso: string): string {
  return monthDayFormatter.format(new Date(iso)).replace('月', '.').replace('日', '')
}

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return articles.value.filter((article) => {
    if (categorySlug.value && article.category?.slug !== categorySlug.value) return false
    if (!kw) return true
    return [article.title, article.summary, article.location, article.category?.name ?? '']
      .join(' ')
      .toLowerCase()
      .includes(kw)
  })
})

const groups = computed(() => {
  const map = new Map<number, Article[]>()
  for (const article of filtered.value) {
    const y = yearOf(article.publish_time)
    if (!map.has(y)) map.set(y, [])
    map.get(y)!.push(article)
  }
  return [...map.entries()]
    .sort((a, b) => b[0] - a[0])
    .map(([year, items]) => ({ year, items }))
})

const categoryChips = computed(() =>
  categories.value.map((c) => ({
    slug: c.slug,
    name: c.name,
    count: articles.value.filter((a) => a.category?.slug === c.slug).length,
  })),
)

const span = computed(() => {
  const years = articles.value.map((a) => yearOf(a.publish_time))
  return years.length ? Math.max(...years) - Math.min(...years) + 1 : 0
})
</script>

<template>
  <div class="cv-page">
    <!-- 页头：与首页区块标题同构 -->
    <header class="cv-section-head cv-page__head">
      <div class="cv-section-head__top">
        <div>
          <p class="cv-section-head__eyebrow">
            <span lang="en">TIMELINE</span> / 时间轴
          </p>
          <h2 class="cv-section-head__title">沿时间倒流，回看每一段旅程</h2>
        </div>
        <p class="cv-section-head__count">共 {{ total }} 篇 · 跨 {{ span }} 年</p>
      </div>
      <div class="cv-section-head__line" aria-hidden="true" />
    </header>

    <!-- 筛选 -->
    <div class="cv-tl__filters">
      <div class="cv-tl__field">
        <span class="cv-tl__field-icon" aria-hidden="true">⌕</span>
        <input
          v-model="keyword"
          type="search"
          autocomplete="off"
          placeholder="输入标题、地点…"
          aria-label="筛选时间轴"
        >
      </div>
      <div class="cv-tl__chips" role="group" aria-label="按分类筛选">
        <button
          type="button"
          class="cv-tl__chip"
          :aria-pressed="!categorySlug"
          @click="categorySlug = ''"
        >
          全部 ({{ articles.length }})
        </button>
        <button
          v-for="c in categoryChips"
          :key="c.slug"
          type="button"
          class="cv-tl__chip"
          :aria-pressed="categorySlug === c.slug"
          @click="categorySlug = c.slug"
        >
          {{ c.name }} ({{ c.count }})
        </button>
      </div>
    </div>

    <div v-if="loading" class="cv-state">正在加载时间轴…</div>
    <div v-else-if="errorMsg" class="cv-state">{{ errorMsg }}</div>
    <div v-else-if="filtered.length === 0" class="cv-state">没有匹配的游记</div>

    <template v-else>
      <section v-for="group in groups" :key="group.year" class="cv-tl__year">
        <h3 class="cv-tl__year-label">
          {{ group.year }}
          <span class="cv-tl__year-count">{{ group.items.length }} 篇</span>
        </h3>

        <ul role="list" class="cv-tl__list">
          <li v-for="article in group.items" :key="article.id" class="cv-tl__item">
            <NuxtLink :to="`/article/${article.slug}`" class="cv-tl__link">
              <span class="cv-tl__dot" aria-hidden="true" />
              <time class="cv-tl__date" :datetime="article.publish_time">
                {{ dayLabel(article.publish_time) }}
              </time>
              <img
                v-if="article.cover_image_url"
                :src="article.cover_image_url"
                alt=""
                width="64"
                height="44"
                loading="lazy"
                class="cv-tl__thumb"
              >
              <span v-else class="cv-tl__thumb cv-tl__thumb--fallback" aria-hidden="true" />
              <span class="cv-tl__title">{{ article.title }}</span>
              <span v-if="article.category" class="cv-tl__cat">{{ article.category.name }}</span>
            </NuxtLink>
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>
