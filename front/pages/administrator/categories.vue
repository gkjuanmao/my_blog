<script setup lang="ts">
/**
 * 分类管理：栏目索引 + 设置面板（视图见 components/admin/CategoryIndex.vue）。
 *
 * 稿件数没有现成的聚合接口，这里用「最多 100 篇」的文章列表在前端计数；
 * 个人博客规模下即精确值（与总览页口径一致）。
 */
import type { Article, PaginatedResponse } from '~/types/api'
import { useCrudTable } from '~/composables/useCrudTable'

definePageMeta({ layout: 'admin' })

const { list, loading, fetchList, submit, remove } = useCrudTable({
  listUrl: '/categories/',
  baseUrl: '/admin/categories',
})

const counts = ref<Record<number, number>>({})
const articleTotal = ref(0)

async function fetchCounts() {
  try {
    const { data } = await useApi().get<PaginatedResponse<Article>>('/admin/articles/', {
      page_size: 100,
    })
    const map: Record<number, number> = {}
    data.items.forEach((item) => {
      const id = item.category?.id
      if (id != null) map[id] = (map[id] ?? 0) + 1
    })
    counts.value = map
    articleTotal.value = data.total
  } catch {
    counts.value = {}
  }
}

const filedCount = computed(() => Object.values(counts.value).reduce((sum, n) => sum + n, 0))
const emptyCount = computed(
  () => list.value.filter(row => (counts.value[row.id] ?? 0) === 0).length,
)
const meta = computed(
  () =>
    `${list.value.length} 个栏目 · ${filedCount.value} 篇已归档 · ${emptyCount.value} 个尚空${
      articleTotal.value > 100 ? '（按最近 100 篇统计）' : ''
    }`,
)

function refresh() {
  fetchList()
  fetchCounts()
}

onMounted(refresh)
</script>

<template>
  <div>
    <AdminMasthead eyebrow="栏目" eyebrow-en="Sections" title="分类管理" :meta="meta">
      <template #actions>
        <NuxtLink class="ad-btn ad-btn--ghost" to="/administrator/articles">按栏目看稿件</NuxtLink>
      </template>
    </AdminMasthead>

    <CategoryIndex
      :list="list"
      :loading="loading"
      :counts="counts"
      :submit="submit"
      :remove="remove"
      @changed="refresh"
    />
  </div>
</template>
