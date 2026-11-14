<script setup lang="ts">
/**
 * 标签管理：索引卡 + 编辑面板（视图见 components/admin/TagIndex.vue）。
 *
 * 标签本身没有「使用次数」字段，这里和分类页同口径：取最近 100 篇文章在前端
 * 累计每个标签被挂了多少次。默认按使用次数倒序，工具带里可切回按名称。
 */
import type { Article, PaginatedResponse } from '~/types/api'
import { useCrudTable } from '~/composables/useCrudTable'

definePageMeta({ layout: 'admin' })

const { list, loading, fetchList, submit, remove } = useCrudTable({
  listUrl: '/tags/',
  baseUrl: '/admin/tags',
})

const counts = ref<Record<number, number>>({})
const query = ref('')
const sortBy = ref<'count' | 'name'>('count')

async function fetchCounts() {
  try {
    const { data } = await useApi().get<PaginatedResponse<Article>>('/admin/articles/', {
      page_size: 100,
    })
    const map: Record<number, number> = {}
    data.items.forEach((item) => {
      item.tags.forEach((tag) => {
        map[tag.id] = (map[tag.id] ?? 0) + 1
      })
    })
    counts.value = map
  } catch {
    counts.value = {}
  }
}

const usedCount = computed(() => list.value.filter(row => (counts.value[row.id] ?? 0) > 0).length)
const meta = computed(
  () => `${list.value.length} 条标签 · ${usedCount.value} 条在用 · 点选一格在右侧编辑`,
)

const visible = computed(() => {
  const word = query.value.trim().toLowerCase()
  const rows = list.value.filter(
    row => !word || row.name.toLowerCase().includes(word) || row.slug.toLowerCase().includes(word),
  )
  return [...rows].sort((a, b) => {
    if (sortBy.value === 'name') return a.name.localeCompare(b.name, 'zh-CN')
    return (
      (counts.value[b.id] ?? 0) - (counts.value[a.id] ?? 0) ||
      a.name.localeCompare(b.name, 'zh-CN')
    )
  })
})

const tagIndex = ref<{ startCreate: () => void } | null>(null)

function refresh() {
  fetchList()
  fetchCounts()
}

onMounted(refresh)
</script>

<template>
  <div class="ad-page">
    <AdminMasthead eyebrow="标签" eyebrow-en="Index" title="标签管理" :meta="meta">
      <template #actions>
        <button class="ad-btn ad-btn--primary" type="button" @click="tagIndex?.startCreate()">
          <AdminIcon name="plus" :size="14" />新建标签
        </button>
      </template>
    </AdminMasthead>

    <div class="ad-toolbar">
      <label class="ad-tool" style="width: 240px">
        <AdminIcon name="search" :size="14" />
        <input v-model="query" type="search" placeholder="搜名称或 slug…" aria-label="搜索标签">
      </label>

      <div class="ad-segs" role="group" aria-label="排序方式">
        <button class="ad-seg" type="button" :aria-pressed="sortBy === 'count'" @click="sortBy = 'count'">
          按使用
        </button>
        <button class="ad-seg" type="button" :aria-pressed="sortBy === 'name'" @click="sortBy = 'name'">
          按名称
        </button>
      </div>

      <span class="ad-toolbar__spacer" />
      <span class="ad-toolbar__note">{{ visible.length }} 条</span>
    </div>

    <TagIndex
      ref="tagIndex"
      :list="visible"
      :loading="loading"
      :counts="counts"
      :submit="submit"
      :remove="remove"
      @changed="refresh"
    />
  </div>
</template>
