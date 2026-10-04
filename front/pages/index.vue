<script setup lang="ts">
import type { Article, PaginatedResponse } from '~/types/api'

const { page, pageSize, clampPage } = usePageQuery()
const articles = ref<Article[]>([])
const total = ref(0)
const loading = ref(true)
const errorMsg = ref('')

async function fetchArticles() {
  loading.value = true
  errorMsg.value = ''
  try {
    const { data } = await useApi().get<PaginatedResponse<Article>>('/articles/', {
      page: page.value,
      page_size: pageSize.value,
    })
    articles.value = data.items
    total.value = data.total
    clampPage(data.total, pageSize.value)
  } catch (e: any) {
    errorMsg.value = e?.message ?? '加载失败'
  } finally {
    loading.value = false
  }
}

watch([page, pageSize], fetchArticles)
await fetchArticles()
</script>

<template>
  <div class="space-y-10">
    <section class="rounded-2xl border border-stone-200 bg-white p-6 shadow-sm dark:border-stone-700 dark:bg-stone-900">
      <div class="flex items-center gap-4">
        <div class="flex h-16 w-16 items-center justify-center rounded-full bg-brand-100 text-2xl text-brand-600 dark:bg-brand-900/40 dark:text-amber-400">旅</div>
        <div>
          <h1 class="text-2xl font-serif font-bold text-stone-900 dark:text-stone-100">旅行游记</h1>
          <p class="text-sm text-stone-500 dark:text-stone-400">记录山川湖海，也收藏人间烟火。</p>
        </div>
      </div>
    </section>

    <div v-if="loading && articles.length === 0" class="py-16 text-center text-sm text-stone-400">加载中…</div>
    <div v-else-if="errorMsg" class="py-16 text-center text-sm text-red-500">{{ errorMsg }}</div>
    <template v-else>
      <div class="grid grid-cols-1 gap-6 sm:grid-cols-2">
        <ArticleCard v-for="article in articles" :key="article.id" :article="article" />
      </div>
      <div v-if="articles.length === 0" class="py-16 text-center text-sm text-stone-400">暂无文章</div>
      <div v-if="total > 0" class="mt-8 flex justify-center">
        <AppPagination v-model:page="page" v-model:page-size="pageSize" :total="total" :reset-page-on-size-change="false" />
      </div>
    </template>
  </div>
</template>
