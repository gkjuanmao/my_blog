<script setup lang="ts">
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
</script>

<template>
  <div class="space-y-10">
    <section data-skin="surface" class="skin-hero rounded-2xl border border-stone-200 bg-white p-6 shadow-sm dark:border-stone-700 dark:bg-stone-900">
      <div class="flex items-center gap-4">
        <div class="flex h-16 w-16 items-center justify-center rounded-full bg-brand-100 text-2xl text-brand-600 dark:bg-brand-900/40 dark:text-amber-400">旅</div>
        <div>
          <h1 class="text-2xl font-serif font-bold text-stone-900 dark:text-stone-100">{{ site.name }}</h1>
          <p class="text-sm text-stone-500 dark:text-stone-400">{{ site.tagline }}</p>
        </div>
      </div>
    </section>

    <ArticleListSection
      v-model:page="page"
      v-model:page-size="pageSize"
      :articles="articles"
      :total="total"
      :loading="loading"
      :error-msg="errorMsg"
      empty-text="暂无文章"
    />
  </div>
</template>