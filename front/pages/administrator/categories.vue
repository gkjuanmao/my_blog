<script setup lang="ts">
/**
 * 分类管理：栏目索引 + 设置面板（视图见 components/admin/CategoryIndex.vue）。
 *
 * 稿件数没有现成的聚合接口，这里用「最多 100 篇」的文章列表在前端计数；
 * 个人博客规模下即精确值（与总览页口径一致）。搜索与排序在页面里做，
 * 这样搜索框能留在统一的工具带里。
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

const query = ref('')
const sortBy = ref<'count' | 'name'>('count')

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

/** 工具带筛选 + 排序：默认按稿件数倒序（存稿最多的栏目先看到） */
const visible = computed(() => {
  const word = query.value.trim().toLowerCase()
  const rows = list.value.filter(
    row =>
      !word || row.name.toLowerCase().includes(word) || row.slug.toLowerCase().includes(word),
  )
  return [...rows].sort((a, b) => {
    if (sortBy.value === 'name') return a.name.localeCompare(b.name, 'zh-CN')
    return (
      (counts.value[b.id] ?? 0) - (counts.value[a.id] ?? 0) ||
      a.name.localeCompare(b.name, 'zh-CN')
    )
  })
})

function refresh() {
  fetchList()
  fetchCounts()
}

onMounted(refresh)
</script>

<template>
  <div class="ad-page">
    <AdminMasthead eyebrow="栏目" eyebrow-en="Sections" title="分类管理" :meta="meta">
      <template #actions>
        <NuxtLink class="ad-btn ad-btn--ghost" to="/administrator/articles">按栏目看稿件</NuxtLink>
      </template>
    </AdminMasthead>

    <div class="ad-toolbar">
      <label class="ad-tool" style="width: 220px">
        <AdminIcon name="search" :size="14" />
        <input v-model="query" type="search" placeholder="搜栏目名或 slug…" aria-label="搜索栏目">
      </label>

      <label class="ad-tool ad-tool--sel" style="min-width: 132px">
        <span class="ad-sr">排序</span>
        <select v-model="sortBy">
          <option value="count">按稿件数排序</option>
          <option value="name">按名称排序</option>
        </select>
      </label>

      <span class="ad-toolbar__spacer" />
      <span class="ad-toolbar__note">删除栏目不会删除文章</span>
    </div>

    <CategoryIndex
      :list="visible"
      :loading="loading"
      :counts="counts"
      :submit="submit"
      :remove="remove"
      @changed="refresh"
    />
  </div>
</template>
