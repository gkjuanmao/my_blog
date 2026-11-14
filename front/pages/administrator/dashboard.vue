<script setup lang="ts">
/**
 * 编辑部总览（设计见 .workbuddy/design/admin-redesign/）。
 *
 * 版式：刊头 → 四项台账（裸数字 + 竖线）→ 编务节奏 + 最新编务 ｜ 待办 + 栏目存稿 + 标签索引。
 * 数据全部来自既有接口，不新增后端能力：
 *   - 全部稿件（page_size=100，用于最近更新、阅读合计、栏目计数、节奏柱）
 *   - 已发布总数（page_size=1，只取 total）
 *   - 分类、标签
 */
import type { Article, Category, PaginatedResponse, Tag } from '~/types/api'

definePageMeta({ layout: 'admin' })

const total = ref(0)
const publishedTotal = ref(0)
const categories = ref<Category[]>([])
const tags = ref<Tag[]>([])
const articles = ref<Article[]>([])
const loading = ref(true)
const errorMsg = ref('')

/** 一次最多取 100 篇：个人博客足够精确；超过时合计阅读标注为「近 100 篇」 */
const FETCH_LIMIT = 100
/** 节奏柱的窗口 */
const RHYTHM_DAYS = 14
/** 标签索引最多铺 15 个，其余收成「+N 条」 */
const TAG_PREVIEW = 15

const { activeCount } = useImportTasks()

onMounted(async () => {
  try {
    const [all, published, cats, tagList] = await Promise.all([
      useApi().get<PaginatedResponse<Article>>('/admin/articles/', {
        page_size: FETCH_LIMIT,
        ordering: '-publish_time',
      }),
      useApi().get<PaginatedResponse<Article>>('/admin/articles/', {
        page_size: 1,
        is_published: true,
      }),
      useApi().get<Category[]>('/categories/'),
      useApi().get<Tag[]>('/tags/'),
    ])
    articles.value = all.data.items
    total.value = all.data.total
    publishedTotal.value = published.data.total
    categories.value = cats.data
    tags.value = tagList.data
  } catch (e) {
    errorMsg.value = errorMessage(e, '加载失败')
  } finally {
    loading.value = false
  }
})

const drafts = computed(() => Math.max(0, total.value - publishedTotal.value))
const exact = computed(() => total.value <= FETCH_LIMIT)
const views = computed(() => articles.value.reduce((sum, item) => sum + (item.views || 0), 0))
const avgViews = computed(() =>
  publishedTotal.value ? (views.value / publishedTotal.value).toFixed(1) : '0',
)

const recent = computed(() => articles.value.slice(0, 6))

/** 每个栏目下的稿件数（按 id 计数），按数量倒序排成台账条形 */
const categoryRows = computed(() => {
  const counts = new Map<number, number>()
  articles.value.forEach((item) => {
    const id = item.category?.id
    if (id != null) counts.set(id, (counts.get(id) ?? 0) + 1)
  })
  const rows = categories.value.map(cat => ({ ...cat, count: counts.get(cat.id) ?? 0 }))
  rows.sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, 'zh-CN'))
  return rows
})
const maxCount = computed(() => Math.max(1, ...categoryRows.value.map(row => row.count)))
const emptyCategories = computed(() => categoryRows.value.filter(row => row.count === 0).length)
/** 默认分类里压着的稿件（提示可执行动作，而不是装饰文案） */
const defaultCategoryCount = computed(
  () => categoryRows.value.find(row => row.slug === 'default-category')?.count ?? 0,
)

const viewsLabel = computed(() => (exact.value ? '累计阅读' : '近 100 篇阅读'))

/** 近 14 天每日发布数：只统计已发布的稿件（草稿没有发布时间） */
const rhythm = computed(() => {
  const byDay = new Map<string, number>()
  articles.value.forEach((item) => {
    if (!item.is_published || !item.publish_time) return
    const key = item.publish_time.slice(0, 10)
    byDay.set(key, (byDay.get(key) ?? 0) + 1)
  })
  const today = new Date()
  const days = Array.from({ length: RHYTHM_DAYS }, (_, index) => {
    const offset = RHYTHM_DAYS - 1 - index
    const date = new Date(today)
    date.setDate(today.getDate() - offset)
    const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(
      date.getDate(),
    ).padStart(2, '0')}`
    return {
      key,
      label: offset === 0 ? '今天' : String(date.getDate()).padStart(2, '0'),
      count: byDay.get(key) ?? 0,
      isToday: offset === 0,
      height: 0,
    }
  })
  const max = Math.max(1, ...days.map(day => day.count))
  days.forEach((day) => {
    day.height = Math.round((day.count / max) * 100)
  })
  return days
})
const monthPublished = computed(() => {
  const now = new Date()
  const prefix = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
  return rhythm.value.filter(day => day.key.startsWith(prefix)).reduce((sum, d) => sum + d.count, 0)
})
/** 近 14 天一根柱子都没有时，画个空图不如直接说明 */
const rhythmTotal = computed(() => rhythm.value.reduce((sum, day) => sum + day.count, 0))

const shownTags = computed(() => tags.value.slice(0, TAG_PREVIEW))
const restTags = computed(() => Math.max(0, tags.value.length - TAG_PREVIEW))

function barWidth(count: number): string {
  return `${Math.round((count / maxCount.value) * 100)}%`
}

const todoDrafts = computed(() => drafts.value > 0)
const todoDefault = computed(() => defaultCategoryCount.value > 0)
</script>

<template>
  <div class="ad-page">
    <AdminMasthead
      eyebrow="总览"
      eyebrow-en="Overview"
      title="编辑部总览"
      :meta="`${total} 篇稿件 · ${publishedTotal} 篇已发布 · ${categories.length} 个栏目 · ${tags.length} 条标签`"
    >
      <template #actions>
        <NuxtLink class="ad-btn ad-btn--ghost" to="/administrator/articles">全部稿件</NuxtLink>
        <NuxtLink class="ad-btn ad-btn--primary" to="/administrator/articles/create">
          <AdminIcon name="plus" :size="14" />写新文章
        </NuxtLink>
      </template>
    </AdminMasthead>

    <div v-if="loading" class="ad-void" style="flex: 1">
      <p>正在翻开台账…</p>
    </div>

    <div v-else-if="errorMsg" class="ad-void" style="flex: 1">
      <p class="ad-error" role="alert">{{ errorMsg }}</p>
      <button class="ad-btn ad-btn--ghost ad-btn--sm" type="button" @click="$router.go(0)">
        重新加载
      </button>
    </div>

    <template v-else>
      <!-- 台账：裸数字 + 竖线，不装卡片 -->
      <section class="ad-ledger" aria-label="稿件概况">
        <div class="ad-ledger__item">
          <p class="ad-ledger__label">总稿件</p>
          <p class="ad-ledger__num">{{ total }}<small>篇</small></p>
          <p class="ad-ledger__note">含草稿 · 本月发布 <b>{{ monthPublished }}</b> 篇</p>
        </div>
        <div class="ad-ledger__item">
          <p class="ad-ledger__label">已发布</p>
          <p class="ad-ledger__num">{{ publishedTotal }}<small>篇</small></p>
          <p class="ad-ledger__note">
            {{ recent.length ? `最近发布 ${formatDateCompact(recent[0]?.publish_time ?? '')}` : '还没有发布' }}
          </p>
        </div>
        <div class="ad-ledger__item">
          <p class="ad-ledger__label">草稿</p>
          <p class="ad-ledger__num">{{ drafts }}<small>篇</small></p>
          <p class="ad-ledger__note">{{ drafts ? '待补完再发布' : '没有待发布的稿件' }}</p>
        </div>
        <div class="ad-ledger__item">
          <p class="ad-ledger__label">{{ viewsLabel }}</p>
          <p class="ad-ledger__num">{{ views }}<small>次</small></p>
          <p class="ad-ledger__note">平均 {{ avgViews }} 次 / 篇</p>
        </div>
      </section>

      <div class="ad-split">
        <div class="ad-split__col">
          <!-- 编务节奏 -->
          <section class="ad-block" aria-labelledby="ad-rhythm-title">
            <div class="ad-block__head">
              <h2 id="ad-rhythm-title">编务节奏</h2>
              <span class="ad-block__count">近 {{ RHYTHM_DAYS }} 天</span>
              <span class="ad-block__link">本月已发 {{ monthPublished }} 篇</span>
            </div>
            <div v-if="rhythmTotal" class="ad-rhythm" role="img" :aria-label="`近 ${RHYTHM_DAYS} 天每日发布数量`">
              <div
                v-for="day in rhythm"
                :key="day.key"
                class="ad-rhythm__bar"
                :class="{ 'is-today': day.isToday }"
                :title="`${day.key} · ${day.count} 篇`"
              >
                <i :style="{ height: `${day.height}%` }" />
                <span>{{ day.label }}</span>
              </div>
            </div>
            <p v-else class="ad-block__note">
              近 {{ RHYTHM_DAYS }} 天没有发布新文章{{ recent[0]?.publish_time ? ` —— 最近一篇在 ${formatDateCompact(recent[0].publish_time)}` : '' }}。
            </p>
          </section>

          <!-- 最新编务 -->
          <section class="ad-block" aria-labelledby="ad-feed-title">
            <div class="ad-block__head">
              <h2 id="ad-feed-title">最新编务</h2>
              <span class="ad-block__count">近 {{ recent.length }} 篇</span>
              <NuxtLink class="ad-block__link" to="/administrator/articles">全部稿件 →</NuxtLink>
            </div>

            <p v-if="!recent.length" class="ad-block__note">
              还没有稿件 ——
              <NuxtLink class="ad-block__link" to="/administrator/articles/create">写第一篇</NuxtLink>。
            </p>
            <ul v-else class="ad-feed">
              <li v-for="item in recent" :key="item.id" class="ad-feed__row">
                <img
                  v-if="item.cover_image_url"
                  class="ad-thumb"
                  :src="item.cover_image_url"
                  alt=""
                >
                <span v-else class="ad-thumb ad-thumb--blank" aria-hidden="true" />
                <span class="ad-feed__text">
                  <p class="ad-feed__title">{{ item.title }}</p>
                  <p class="ad-feed__meta">
                    {{ item.category?.name ?? '未分类' }} ·
                    {{ item.is_published ? formatDateCompact(item.publish_time) : '草稿' }}
                    <template v-if="item.is_published"> · {{ item.views }} 次阅读</template>
                  </p>
                </span>
                <span
                  class="ad-status ad-feed__status"
                  :class="{ 'ad-status--draft': !item.is_published }"
                >
                  <i aria-hidden="true" />{{ item.is_published ? '已发布' : '草稿' }}
                </span>
                <NuxtLink class="ad-feed__go" :to="`/administrator/articles/edit/${item.id}`">
                  编辑
                </NuxtLink>
              </li>
            </ul>
          </section>
        </div>

        <div class="ad-split__aside">
          <!-- 待办：三条可点的动作 -->
          <section class="ad-block" aria-labelledby="ad-todo-title">
            <div class="ad-block__head">
              <h2 id="ad-todo-title">待办</h2>
              <span class="ad-block__count">
                {{ (todoDrafts ? 1 : 0) + (todoDefault ? 1 : 0) + (activeCount ? 1 : 0) }} 件
              </span>
            </div>

            <NuxtLink v-if="todoDrafts" class="ad-todo" to="/administrator/articles?status=false">
              <span class="ad-todo__bar" aria-hidden="true" />
              <span class="ad-todo__text">
                <b>{{ drafts }} 篇草稿还没发布</b>
                <span>补完就能上线</span>
              </span>
              <span class="ad-todo__go">去处理</span>
            </NuxtLink>

            <NuxtLink
              v-if="todoDefault"
              class="ad-todo"
              to="/administrator/articles?category=default-category"
            >
              <span class="ad-todo__bar ad-todo__bar--pine" aria-hidden="true" />
              <span class="ad-todo__text">
                <b>{{ defaultCategoryCount }} 篇还在「默认分类」</b>
                <span>归类后前台才能按栏目浏览</span>
              </span>
              <span class="ad-todo__go">去归类</span>
            </NuxtLink>

            <NuxtLink v-if="activeCount" class="ad-todo" to="/administrator/tasks">
              <span class="ad-todo__bar ad-todo__bar--mute" aria-hidden="true" />
              <span class="ad-todo__text">
                <b>{{ activeCount }} 个导入任务进行中</b>
                <span>队列串行执行，点开看进度</span>
              </span>
              <span class="ad-todo__go">看进度</span>
            </NuxtLink>

            <p v-if="!todoDrafts && !todoDefault && !activeCount" class="ad-block__note">
              没有待办 —— 草稿都发完了，栏目也归好了。
            </p>
          </section>

          <!-- 栏目存稿 -->
          <section class="ad-block" aria-labelledby="ad-cats-title">
            <div class="ad-block__head">
              <h2 id="ad-cats-title">栏目存稿</h2>
              <span class="ad-block__count">{{ categories.length }} 个</span>
              <NuxtLink class="ad-block__link" to="/administrator/categories">管理 →</NuxtLink>
            </div>

            <div style="margin-top: 10px">
              <div v-for="row in categoryRows" :key="row.id" class="ad-catrow">
                <NuxtLink class="ad-catrow__name" :to="`/administrator/articles?category=${row.slug}`">
                  {{ row.name }}
                </NuxtLink>
                <span class="ad-catrow__bar">
                  <i
                    :class="{ 'is-alert': row.slug === 'default-category' }"
                    :style="{ width: barWidth(row.count) }"
                  />
                </span>
                <span class="ad-catrow__num">{{ row.count }}</span>
              </div>
            </div>
            <p v-if="emptyCategories" class="ad-block__note">
              {{ emptyCategories }} 个栏目还没有稿件。
            </p>
          </section>

          <!-- 标签索引 -->
          <section class="ad-block" aria-labelledby="ad-tags-title">
            <div class="ad-block__head">
              <h2 id="ad-tags-title">标签索引</h2>
              <span class="ad-block__count">{{ tags.length }} 条</span>
              <NuxtLink class="ad-block__link" to="/administrator/tags">管理 →</NuxtLink>
            </div>
            <div v-if="tags.length" class="ad-chips">
              <NuxtLink
                v-for="tag in shownTags"
                :key="tag.id"
                class="ad-chips__item"
                :class="{ 'ad-chips__item--sys': tag.slug === 'default-tag' }"
                to="/administrator/tags"
              >
                <b>#</b>{{ tag.name }}
              </NuxtLink>
              <NuxtLink v-if="restTags" class="ad-chips__item ad-chips__item--more" to="/administrator/tags">
                +{{ restTags }} 条
              </NuxtLink>
            </div>
            <p v-else class="ad-block__note">还没有标签。</p>
          </section>
        </div>
      </div>
    </template>
  </div>
</template>
