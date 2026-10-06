<script setup lang="ts">
import type { Article, Category, PaginatedResponse } from '~/types/api'
import { useArticleList } from '~/composables/useArticleList'

const route = useRoute()
const slug = computed(() => route.params.slug as string)

const { page, pageSize, articles, total, loading, errorMsg, load } = useArticleList()
const category = ref<Category | null>(null)

useSeoMeta({
  title: () => (category.value ? `分类：${category.value.name}` : '分类'),
  description: () =>
    category.value?.description || `「${category.value?.name ?? '分类'}」下的全部文章`,
})

async function fetchData() {
  // 分类实体与列表必须同一版本：实体在 loader 内取好，但只在「本次响应仍是最新」时应用
  let resolved: Category | null = null
  await load(
    async (pageNum, size) => {
      const [catRes, artRes] = await Promise.all([
        useApi().get<Category[]>('/categories/'),
        useApi().get<PaginatedResponse<Article>>('/articles/', {
          page: pageNum,
          page_size: size,
          category_slug: slug.value,
        }),
      ])
      resolved = catRes.data.find(c => c.slug === slug.value) ?? null
      return artRes.data
    },
    () => {
      category.value = resolved
    },
  )
}

watch([page, pageSize], fetchData)
// 切换分类：清掉页码并重新拉取（页码本就在第 1 页时 query 无变化，需手动触发）
watch(slug, () => {
  if (page.value !== 1) page.value = 1
  else fetchData()
})
await fetchData()
</script>

<template>
  <div class="space-y-8">
    <h1 class="text-2xl font-serif font-bold text-stone-900 dark:text-stone-100">
      {{ category ? category.name : '分类不存在' }}
    </h1>

    <ArticleListSection
      v-model:page="page"
      v-model:page-size="pageSize"
      :articles="articles"
      :total="total"
      :loading="loading"
      :error-msg="errorMsg"
      empty-text="该分类下暂无文章"
    />
  </div>
</template>