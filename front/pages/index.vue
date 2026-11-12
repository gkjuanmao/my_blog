<script setup lang="ts">
/**
 * 公开首页 · 卷首式版式。
 *
 * 数据沿用 `useArticleList()` + `usePageQuery()`（分页状态同步 URL query，page_size 默认 10），
 * 不新开数据通道。版式规则对任意 page_size 都成立：
 *   第 1 条 → 精选（12 列，左 40% 面板 + 右 60% 照片）
 *   最后 1 条 → 宽卡（12 列 4:1）
 *   中间 → 标准卡（6 列，2 列栅格）
 *   条目数 < 3 → 全部降级为标准卡（避免出现「只有一张精选卡」的怪图）
 */
import type { Article, PaginatedResponse } from '~/types/api'
import { useArticleList } from '~/composables/useArticleList'

const { site } = useAppConfig()
const { page, pageSize, articles, total, loading, errorMsg, load } = useArticleList()

useSeoMeta({
  title: () => site.name,
  description: site.tagline,
})

function fetchArticles() {
  return load(async (pageNum, size) => {
    const { data } = await useApi().get<PaginatedResponse<Article>>('/articles/', {
      page: pageNum,
      page_size: size,
    })
    return data
  })
}

watch([page, pageSize], fetchArticles)
await fetchArticles()

const lastPage = computed(() => Math.max(1, Math.ceil(total.value / Math.max(1, pageSize.value))))
/** URL 手改成越界页码（或文章被删）时，SSR 阶段也要给出可读的说明与回头路 */
const outOfRange = computed(() => total.value > 0 && page.value > lastPage.value)

const heroArticle = computed<Article | null>(() => articles.value[0] ?? null)
const sealChar = computed(() => site.name.trim().charAt(0))

/** 全局序号（不是页内序号，否则「01 / 36」会说谎） */
function globalIndex(i: number): string {
  return String((page.value - 1) * pageSize.value + i + 1).padStart(2, '0')
}

interface CoverSlot {
  article: Article
  variant: 'featured' | 'std' | 'wide'
  index: string
}

const slots = computed<CoverSlot[]>(() => {
  const list = articles.value
  if (list.length < 3) {
    return list.map((article, i) => ({ article, variant: 'std' as const, index: globalIndex(i) }))
  }
  const last = list.length - 1
  return list.map((article, i) => ({
    article,
    variant: i === 0 ? ('featured' as const) : i === last ? ('wide' as const) : ('std' as const),
    index: globalIndex(i),
  }))
})

/* 动效：入场（一次性）+ 卡片揭示；滚动相关全部在 layouts/default.vue 的单例监听里 */
const gridEl = ref<HTMLElement | null>(null)
const revealSignature = computed(
  () => `${page.value}|${pageSize.value}|${articles.value.map((a) => a.id).join(',')}`,
)
useCoverEntrance()
useCoverReveal(gridEl, () => revealSignature.value)

/** 错误态重试：只重拉当前页，不整页 refresh（否则 hero 大图会重走一遍加载） */
function retry() {
  void fetchArticles()
}

/**
 * 翻页：内容在原地替换，读屏用户得不到任何提示（4.1.3），
 * 所以把焦点交给 `#journal`（tabindex="-1"）并滚到区块顶部。
 * 只在用户点了页码时触发，首屏 / SSR 不做，避免抢焦点。
 */
async function onPageChange(next: number) {
  page.value = next
  await nextTick()
  const section = document.getElementById('journal')
  if (!section) return
  section.focus({ preventScroll: true })
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  section.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'start' })
}

function onPageSizeChange(next: number) {
  // usePageQuery 的 pageSize setter 会一并把 page 重置到 1
  pageSize.value = next
}
</script>

<template>
  <div class="cv-home">
    <CoverHero :article="heroArticle" :total="total" :site-name="site.name" />

    <section id="journal" class="cv-section" tabindex="-1" aria-labelledby="journal-heading">
      <CoverSectionHead :total="total" />

      <!-- 三态语义与 ArticleListSection 保持字面一致（判断顺序也一样） -->
      <div v-if="loading && articles.length === 0" class="cv-state" role="status">
        正在加载游记…
      </div>

      <div v-else-if="errorMsg" class="cv-state" role="alert">
        <p class="cv-state__msg">{{ errorMsg }}</p>
        <button type="button" class="cv-state__retry" @click="retry">重试</button>
      </div>

      <div v-else-if="total === 0" class="cv-state" role="status">
        <p>还没有发布任何游记</p>
      </div>

      <div v-else-if="outOfRange" class="cv-state" role="status">
        <p>这一页不存在（共 {{ lastPage }} 页）</p>
        <button type="button" class="cv-state__retry" @click="onPageChange(lastPage)">
          回到第 {{ lastPage }} 页
        </button>
      </div>

      <template v-else>
        <!-- 翻页时旧卡片不卸载：aria-busy + 降透明度，高度不变 = 零 CLS -->
        <ul ref="gridEl" class="cv-grid" :aria-busy="loading ? 'true' : 'false'">
          <li
            v-for="slot in slots"
            :key="slot.article.id"
            class="cv-grid__item"
            :class="{
              'cv-grid__item--featured': slot.variant === 'featured',
              'cv-grid__item--wide': slot.variant === 'wide',
            }"
          >
            <CoverCard
              :article="slot.article"
              :variant="slot.variant"
              :index="slot.index"
              :total="total"
              :page="page"
              :is-last-page="page >= lastPage"
              :seal-char="sealChar"
            />
          </li>
        </ul>

        <CoverPager
          :page="page"
          :page-size="pageSize"
          :total="total"
          :loading="loading"
          @update:page="onPageChange"
          @update:page-size="onPageSizeChange"
        />
      </template>
    </section>
  </div>
</template>
