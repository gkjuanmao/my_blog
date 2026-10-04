<script setup lang="ts">
import type { Article, Category, PaginatedResponse } from '~/types/api'

const route = useRoute()
const slug = computed(() => route.params.slug as string)

const { page, pageSize, clampPage } = usePageQuery()
const category = ref<Category | null>(null)
const articles = ref<Article[]>([])
const total = ref(0)
const loading = ref(true)
const errorMsg = ref('')

async function fetchData() {
  loading.value = true
  errorMsg.value = ''
  try {
    const [catRes, artRes] = await Promise.all([
      useApi().get<Category[]>('/categories/'),
      useApi().get<PaginatedResponse<Article>>('/articles/', {
        page: page.value,
        page_size: pageSize.value,
        category_slug: slug.value,
      }),
    ])
    category.value = catRes.data.find((c) => c.slug === slug.value) ?? null
    articles.value = artRes.data.items
    total.value = artRes.data.total
    clampPage(artRes.data.total, pageSize.value)
  } catch (e: any) {
    errorMsg.value = e?.message ?? '加载失败'
  } finally {
    loading.value = false
  }
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

    <div v-if="loading && articles.length === 0" class="py-16 text-center text-sm text-stone-400">加载中…</div>
    <div v-else-if="errorMsg" class="py-16 text-center text-sm text-red-500">{{ errorMsg }}</div>
    <template v-else>
      <div class="grid grid-cols-1 gap-6 sm:grid-cols-2">
        <ArticleCard v-for="article in articles" :key="article.id" :article="article" />
      </div>
      <div v-if="articles.length === 0" class="py-16 text-center text-sm text-stone-400">该分类下暂无文章</div>
      <div v-if="total > 0" class="mt-8 flex justify-center">
        <AppPagination v-model:page="page" v-model:page-size="pageSize" :total="total" :reset-page-on-size-change="false" />
      </div>
    </template>
  </div>
</template>
