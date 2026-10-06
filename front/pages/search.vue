<script setup lang="ts">
import type { Article, PaginatedResponse } from '~/types/api'

const route = useRoute()
const router = useRouter()
const { page, pageSize, clampPage } = usePageQuery()

// URL 中的关键词是唯一数据源；输入框是独立的可编辑副本
const keyword = computed(() => ((route.query.keyword as string) ?? '').trim())
const keywordInput = ref(keyword.value)
const searched = computed(() => keyword.value !== '')

useSeoMeta({
  title: () => (keyword.value ? `搜索：${keyword.value}` : '搜索'),
  description: () => (keyword.value ? `与「${keyword.value}」相关的文章` : '搜索文章'),
})

const results = ref<Article[]>([])
const total = ref(0)
const loading = ref(false)
const errorMsg = ref('')
const guard = useRequestGuard()

async function doSearch() {
  if (!searched.value) return
  const seq = guard.begin()
  loading.value = true
  errorMsg.value = ''
  try {
    const { data } = await useApi().get<PaginatedResponse<Article>>('/articles/search/', {
      keyword: keyword.value,
      page: page.value,
      page_size: pageSize.value,
    })
    if (!guard.isLatest(seq)) return
    results.value = data.items
    total.value = data.total
    clampPage(data.total, pageSize.value)
  } catch (e) {
    if (!guard.isLatest(seq)) return
    errorMsg.value = errorMessage(e, '搜索失败')
  } finally {
    if (guard.isLatest(seq)) loading.value = false
  }
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

    <div v-if="!searched && !loading" class="py-16 text-center text-sm text-stone-400">输入关键词搜索文章</div>
    <div v-if="loading" class="py-16 text-center text-sm text-stone-400">搜索中…</div>
    <div v-if="errorMsg" class="py-16 text-center text-sm text-red-500">{{ errorMsg }}</div>
    <div v-if="searched && !loading && !errorMsg && results.length === 0" class="py-16 text-center text-sm text-stone-400">
      未找到相关文章
    </div>
    <div v-if="searched && results.length > 0" class="grid grid-cols-1 gap-6 sm:grid-cols-2">
      <ArticleCard v-for="article in results" :key="article.id" :article="article" />
    </div>
    <div v-if="searched && total > 0" class="mt-8 flex justify-center">
      <AppPagination v-model:page="page" v-model:page-size="pageSize" :total="total" :reset-page-on-size-change="false" />
    </div>
  </div>
</template>
