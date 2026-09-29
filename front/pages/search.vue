<script setup lang="ts">
import type { Article, PaginatedResponse } from '~/types/api'

const keyword = ref('')
const results = ref<Article[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)
const searched = ref(false)
const loading = ref(false)
const errorMsg = ref('')

async function doSearch(resetPage = false) {
  const kw = keyword.value.trim()
  if (!kw) return
  if (resetPage) page.value = 1
  loading.value = true
  errorMsg.value = ''
  try {
    const { data } = await useApi().get<PaginatedResponse<Article>>('/articles/search/', {
      keyword: kw,
      page: page.value,
      page_size: pageSize.value,
    })
    results.value = data.items
    total.value = data.total
    searched.value = true
  } catch (e: any) {
    errorMsg.value = e?.message ?? '搜索失败'
  } finally {
    loading.value = false
  }
}

// 翻页/改每页数量时沿用当前关键词重新查询
watch([page, pageSize], () => {
  if (searched.value) doSearch()
})
</script>

<template>
  <div class="space-y-8">
    <div class="flex flex-col gap-3 sm:flex-row sm:items-center">
      <el-input
        v-model="keyword"
        placeholder="输入关键词，回车搜索文章标题…"
        clearable
        size="large"
        @keyup.enter="doSearch(true)"
      />
      <el-button type="warning" size="large" @click="doSearch(true)">搜索</el-button>
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
      <AppPagination v-model:page="page" v-model:page-size="pageSize" :total="total" />
    </div>
  </div>
</template>
