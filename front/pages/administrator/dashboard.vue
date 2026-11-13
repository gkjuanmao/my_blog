<script setup lang="ts">
/**
 * 编辑部总览（设计见 .workbuddy/design/admin/README.md）。
 *
 * 版式：在编卷首 → 四项台账（裸数字 + 竖线）→ 最新编务 + 栏目存稿 → 标签索引。
 * 数据全部来自既有接口，不新增后端能力：
 *   - 全部稿件（page_size=100，用于最近更新、阅读合计、栏目计数）
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

const latest = computed<Article | null>(() => articles.value[0] ?? null)
const recent = computed(() => articles.value.slice(0, 6))

/** 每个栏目下的稿件数（按 id 计数），并按数量倒序排列成台账条形 */
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
/** 默认分类里压着的稿件（提示可执行动作，而不是装饰文案） */
const defaultCategoryCount = computed(
  () => categoryRows.value.find(row => row.slug === 'default-category')?.count ?? 0,
)

const viewsLabel = computed(() => (exact.value ? '累计阅读' : '近 100 篇阅读'))

function barWidth(count: number): string {
  return `${Math.round((count / maxCount.value) * 100)}%`
}
</script>

<template>
  <div>
    <AdminMasthead
      eyebrow="总览"
      eyebrow-en="Overview"
      title="编辑部总览"
      :meta="`${total} 篇稿件 · ${publishedTotal} 篇已发布 · ${categories.length} 个栏目 · ${tags.length} 条标签`"
    />

    <div
      v-if="loading"
      class="ad-loading"
      style="padding: 60px 0; text-align: center; color: var(--hp-ink-3)"
    >
      正在翻开台账…
    </div>

    <div v-else-if="errorMsg" role="alert" style="padding: 40px 0">
      <p class="ad-error">{{ errorMsg }}</p>
      <button class="ad-btn ad-btn--ghost ad-btn--sm" type="button" style="margin-top: 14px" @click="$router.go(0)">
        重新加载
      </button>
    </div>

    <template v-else>
      <!-- 在编卷首：最新一篇的封面，沿用首页的暗底 + 金色 eyebrow -->
      <article v-if="latest" class="ad-lead">
        <img
          v-if="latest.cover_image_url"
          class="ad-lead__photo"
          :src="latest.cover_image_url"
          alt=""
        >
        <div class="ad-lead__shade" aria-hidden="true" />
        <div class="ad-lead__body">
          <p class="ad-lead__eyebrow">在编卷首 <span>Latest entry</span></p>
          <h2>{{ latest.title }}</h2>
          <p class="ad-lead__meta">
            {{ formatDateCompact(latest.publish_time) }}
            <template v-if="latest.category"> · {{ latest.category.name }}</template>
            · {{ latest.views }} 次阅读
          </p>
          <div class="ad-lead__acts">
            <NuxtLink class="ad-lead__btn" :to="`/administrator/articles/edit/${latest.id}`">
              继续编辑
            </NuxtLink>
            <NuxtLink class="ad-lead__more" :to="`/article/${latest.slug}`" target="_blank">
              查看详情 ↗
            </NuxtLink>
          </div>
        </div>
      </article>

      <!-- 台账：裸数字 + 竖线，不装卡片 -->
      <section class="ad-ledger" aria-label="稿件概况">
        <div class="ad-ledger__item">
          <p class="ad-ledger__label">总稿件</p>
          <p class="ad-ledger__num">{{ total }}<small>篇</small></p>
          <p class="ad-ledger__note">全部稿件（含草稿）</p>
        </div>
        <div class="ad-ledger__item">
          <p class="ad-ledger__label">已发布</p>
          <p class="ad-ledger__num">{{ publishedTotal }}<small>篇</small></p>
          <p class="ad-ledger__note">
            {{ latest ? `最近发布 ${formatDateCompact(latest.publish_time)}` : '还没有发布' }}
          </p>
        </div>
        <div class="ad-ledger__item">
          <p class="ad-ledger__label">草稿</p>
          <p class="ad-ledger__num">{{ drafts }}<small>篇</small></p>
          <p class="ad-ledger__note">
            {{ drafts ? '待补完再发布' : '没有待发布的稿件' }}
          </p>
        </div>
        <div class="ad-ledger__item">
          <p class="ad-ledger__label">{{ viewsLabel }}</p>
          <p class="ad-ledger__num">{{ views }}<small>次</small></p>
          <p class="ad-ledger__note">平均 {{ avgViews }} 次 / 篇</p>
        </div>
      </section>

      <div class="ad-columns">
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
                class="ad-feed__thumb"
                :src="item.cover_image_url"
                alt=""
              >
              <span v-else class="ad-feed__thumb" aria-hidden="true" />
              <div class="ad-feed__text">
                <p class="ad-feed__title">{{ item.title }}</p>
                <p class="ad-feed__meta">
                  {{ item.category?.name ?? '未分类' }} · {{ formatDateCompact(item.publish_time) }}
                </p>
              </div>
              <span
                class="ad-status ad-feed__status"
                :class="{ 'ad-status--draft': !item.is_published }"
              >
                <i aria-hidden="true" />{{ item.is_published ? '已发布' : '草稿' }}
              </span>
            </li>
          </ul>
        </section>

        <section class="ad-block" aria-labelledby="ad-cat-title">
          <div class="ad-block__head">
            <h2 id="ad-cat-title">栏目存稿</h2>
            <span class="ad-block__count">{{ categories.length }} 个</span>
            <NuxtLink class="ad-block__link" to="/administrator/categories">管理栏目 →</NuxtLink>
          </div>

          <ul class="ad-catbars">
            <li v-for="row in categoryRows" :key="row.id" class="ad-catbar">
              <span class="ad-catbar__name">
                <NuxtLink :to="`/administrator/articles?category=${row.slug}`">{{ row.name }}</NuxtLink>
              </span>
              <span class="ad-catbar__spark"><i :style="{ width: barWidth(row.count) }" /></span>
              <span class="ad-catbar__num">{{ row.count }} 篇</span>
            </li>
          </ul>
          <p v-if="defaultCategoryCount" class="ad-block__note">
            {{ defaultCategoryCount }} 篇还在「默认分类」里。给它们挑个栏目，前台才能按分类浏览。
          </p>
        </section>
      </div>

      <section class="ad-block" style="margin-top: 48px" aria-labelledby="ad-tags-title">
        <div class="ad-block__head">
          <h2 id="ad-tags-title">标签索引</h2>
          <span class="ad-block__count">{{ tags.length }} 条</span>
          <NuxtLink class="ad-block__link" to="/administrator/tags">管理标签 →</NuxtLink>
        </div>
        <div v-if="tags.length" class="ad-tagstrip">
          <NuxtLink
            v-for="tag in tags"
            :key="tag.id"
            class="ad-chip"
            :class="{ 'ad-chip--sys': tag.slug === 'default-tag' }"
            to="/administrator/tags"
          >
            # {{ tag.name }}
          </NuxtLink>
        </div>
        <p v-else class="ad-block__note">还没有标签。</p>
      </section>
    </template>
  </div>
</template>
