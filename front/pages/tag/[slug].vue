<script setup lang="ts">
import type { Article, PaginatedResponse, Tag } from '~/types/api'
import { useArticleList } from '~/composables/useArticleList'

const route = useRoute()
const slug = computed(() => route.params.slug as string)

const { page, pageSize, articles, total, loading, errorMsg, load } = useArticleList()
const tag = ref<Tag | null>(null)

useSeoMeta({
  title: () => (tag.value ? `标签：${tag.value.name}` : '标签'),
  description: () => `标签「${tag.value?.name ?? '标签'}」下的全部文章`,
})

async function fetchData() {
  // 标签实体与列表必须同一版本：实体在 loader 内取好，但只在「本次响应仍是最新」时应用
  let resolved: Tag | null = null
  await load(
    async (pageNum, size) => {
      const [tagRes, artRes] = await Promise.all([
        useApi().get<Tag[]>('/tags/'),
        useApi().get<PaginatedResponse<Article>>('/articles/', {
          page: pageNum,
          page_size: size,
          tag_slug: slug.value,
        }),
      ])
      resolved = tagRes.data.find(t => t.slug === slug.value) ?? null
      return artRes.data
    },
    () => {
      tag.value = resolved
    },
  )
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

    <ArticleListSection
      v-model:page="page"
      v-model:page-size="pageSize"
      :articles="articles"
      :total="total"
      :loading="loading"
      :error-msg="errorMsg"
      empty-text="该标签下暂无文章"
    />
  </div>
</template>