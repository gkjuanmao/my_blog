<script setup lang="ts">
import type { Article, PaginatedResponse, Tag } from '~/types/api'

const route = useRoute()
const slug = computed(() => route.params.slug as string)

const { page, pageSize, clampPage } = usePageQuery()
const tag = ref<Tag | null>(null)
const articles = ref<Article[]>([])
const total = ref(0)
const loading = ref(true)
const errorMsg = ref('')

async function fetchData() {
  loading.value = true
  errorMsg.value = ''
  try {
    const [tagRes, artRes] = await Promise.all([
      useApi().get<Tag[]>('/tags/'),
      useApi().get<PaginatedResponse<Article>>('/articles/', {
        page: page.value,
        page_size: pageSize.value,
        tag_slug: slug.value,
      }),
    ])
    tag.value = tagRes.data.find((t) => t.slug === slug.value) ?? null
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
// 切换标签：清掉页码并重新拉取（页码本就在第 1 页时 query 无变化，需手动触发）
watch(slug, () => {
  if (page.value !== 1) page.value = 1
  else fetchData()
})
await fetchData()
</script>

<template>
  <div class="space-y-8">
    <h1 class="text-2xl font-serif font-bold text-stone-900 dark:text-stone-100">
      # {{ tag ? tag.name : '标签不存在' }}
    </h1>

    <div v-if="loading && articles.length === 0" class="py-16 text-center text-sm text-stone-400">加载中…</div>
    <div v-else-if="errorMsg" class="py-16 text-center text-sm text-red-500">{{ errorMsg }}</div>
    <template v-else>
      <div class="grid grid-cols-1 gap-6 sm:grid-cols-2">
        <ArticleCard v-for="article in articles" :key="article.id" :article="article" />
      </div>
      <div v-if="articles.length === 0" class="py-16 text-center text-sm text-stone-400">该标签下暂无文章</div>
      <div v-if="total > 0" class="mt-8 flex justify-center">
        <AppPagination v-model:page="page" v-model:page-size="pageSize" :total="total" :reset-page-on-size-change="false" />
      </div>
    </template>
  </div>
</template>
