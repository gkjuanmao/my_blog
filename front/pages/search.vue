<script setup lang="ts">
import type { Article, PaginatedResponse } from '~/types/api'
import { useArticleList } from '~/composables/useArticleList'

const route = useRoute()
const router = useRouter()

// URL 中的关键词是唯一数据源；输入框是独立的可编辑副本
const keyword = computed(() => ((route.query.keyword as string) ?? '').trim())
const keywordInput = ref(keyword.value)
const searched = computed(() => keyword.value !== '')

const { page, pageSize, articles, total, loading, errorMsg, load } = useArticleList({
  fallbackMessage: '搜索失败',
})

useSeoMeta({
  title: () => (keyword.value ? `搜索：${keyword.value}` : '搜索'),
  description: () => (keyword.value ? `与「${keyword.value}」相关的文章` : '搜索文章'),
})

async function doSearch() {
  if (!searched.value) return
  await load(async (pageNum, size) => {
    const { data } = await useApi().get<PaginatedResponse<Article>>('/articles/search/', {
      keyword: keyword.value,
      page: pageNum,
      page_size: size,
    })
    return data
  })
}

/** 复制当前 query 中的字符串项，供改写后写回 URL */
function collectQuery(): Record<string, string> {
  const query: Record<string, string> = {}
  for (const [key, value] of Object.entries(route.query)) {
    if (typeof value === 'string') query[key] = value
  }
  return query
}

/** 发起搜索：写入 URL（页码归 1），由 URL 变化统一驱动拉取 */
function submitSearch() {
  const kw = keywordInput.value.trim()
  if (!kw) return
  if (kw !== keyword.value) {
    // 新关键词用 push，便于后退回上一次结果
    const query = collectQuery()
    query.keyword = kw
    delete query.page
    router.push({ query })
    return
  }
  // 关键词未变：需要归位到第 1 页时改 URL，否则直接刷新（避免 query 无变化时不触发拉取）
  if (page.value !== 1) {
    const query = collectQuery()
    delete query.page
    router.replace({ query })
  } else {
    doSearch()
  }
}

// 关键词在 URL 变化（后退 / 前进 / 新搜索）时同步输入框
watch(() => route.query.keyword, (value) => {
  keywordInput.value = typeof value === 'string' ? value : ''
})

// 翻页 / 改每页条数 / 换关键词统一重新查询
watch([keyword, page, pageSize], doSearch)

// 首屏 URL 带关键词时自动搜索（含 SSR 预取）
if (searched.value) await doSearch()
</script>

<template>
  <div class="space-y-8">
    <div class="flex flex-col gap-3 sm:flex-row sm:items-center">
      <el-input
        v-model="keywordInput"
        placeholder="输入关键词，回车搜索文章标题…"
        clearable
        size="large"
        @keyup.enter="submitSearch"
      />
      <el-button type="warning" size="large" @click="submitSearch">搜索</el-button>
    </div>

    <!-- 搜索页的三态语义与其余列表页不同（未搜索 / 搜索中 / 无结果），故不复用 ArticleListSection -->
    <div v-if="!searched && !loading" class="py-16 text-center text-sm text-stone-400">输入关键词搜索文章</div>
    <div v-if="loading" class="py-16 text-center text-sm text-stone-400">搜索中…</div>
    <div v-if="errorMsg" class="py-16 text-center text-sm text-red-500">{{ errorMsg }}</div>
    <div v-if="searched && !loading && !errorMsg && articles.length === 0" class="py-16 text-center text-sm text-stone-400">
      未找到相关文章
    </div>
    <ArticleGrid v-if="searched" :articles="articles" />
    <div v-if="searched && total > 0" class="mt-8 flex justify-center">
      <AppPagination v-model:page="page" v-model:page-size="pageSize" :total="total" :reset-page-on-size-change="false" />
    </div>
  </div>
</template>