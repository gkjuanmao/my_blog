<script setup lang="ts">
/**
 * 后台文章列表的移动端卡片视图（FE-09 从 `pages/administrator/articles/index.vue` 拆出）。
 * 与桌面表格共用页面的 `selectedIds`（受控），只上报交互。
 */
import type { Article } from '~/types/api'

defineProps<{
  articles: Article[]
  loading: boolean
  selectedIds: number[]
}>()

const emit = defineEmits<{
  toggleSelect: [id: number]
  edit: [id: number]
  delete: [row: Article]
}>()
</script>

<template>
  <div v-loading="loading" class="space-y-3 md:hidden">
    <div
      v-for="row in articles"
      :key="row.id"
      class="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-700 dark:bg-stone-900"
    >
      <div class="flex items-start justify-between gap-3">
        <div class="flex items-start gap-2">
          <el-checkbox
            :model-value="selectedIds.includes(row.id)"
            @change="emit('toggleSelect', row.id)"
          />
          <h3 class="font-medium text-stone-900 dark:text-stone-100">{{ row.title }}</h3>
        </div>
        <el-tag :type="row.is_published ? 'success' : 'info'" size="small">
          {{ row.is_published ? '已发布' : '草稿' }}
        </el-tag>
      </div>
      <div class="mt-2 space-y-1 text-xs text-stone-500 dark:text-stone-400">
        <div>分类：{{ row.category?.name ?? '—' }}</div>
        <div>发布时间：{{ formatDateTime(row.publish_time) }}</div>
      </div>
      <div class="mt-3 flex justify-end gap-2">
        <el-button link type="primary" @click="emit('edit', row.id)">编辑</el-button>
        <el-button link type="danger" @click="emit('delete', row)">删除</el-button>
      </div>
    </div>
    <div v-if="!loading && articles.length === 0" class="py-8 text-center text-sm text-stone-400">
      暂无文章
    </div>
  </div>
</template>