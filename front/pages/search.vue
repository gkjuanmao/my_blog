<script setup lang="ts">
import type { Article } from '~/types/api'

const keyword = ref('')
const results = ref<Article[]>([])
const searched = ref(false)
const loading = ref(false)
const errorMsg = ref('')

async function doSearch() {
  const kw = keyword.value.trim()
  if (!kw) return
  loading.value = true
  errorMsg.value = ''
  try {
    const { data } = await useApi().get<Article[]>('/articles/search/', { keyword: kw })
    results.value = data
    searched.value = true
  } catch (e: any) {
    errorMsg.value = e?.message ?? '搜索失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="space-y-8">
    <div class="flex items-center gap-3">
      <el-input
        v-model="keyword"
        placeholder="输入关键词，回车搜索文章标题…"
        clearable
        size="large"
        @keyup.enter="doSearch"
      />
      <el-button type="warning" size="large" @click="doSearch">搜索</el-button>
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
  </div>
</template>
