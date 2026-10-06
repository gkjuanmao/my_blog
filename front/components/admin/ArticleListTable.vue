<script setup lang="ts">
/**
 * 后台文章列表的桌面表格（FE-09 从 `pages/administrator/articles/index.vue` 拆出）。
 *
 * 勾选状态由页面持有（`selectedIds`），表格只做展示与事件上报 —— 因此**不用** el-table
 * 自带的 `type="selection"`（那会把勾选状态藏在组件内部，页面就得靠 ref 反控表格）；
 * 改用受控的 el-checkbox 列，表头同样是受控的「全选本页」复选框。
 */
import type { Article } from '~/types/api'

const props = defineProps<{
  articles: Article[]
  loading: boolean
  /** 当前勾选的文章 id（页面持有） */
  selectedIds: number[]
}>()

const emit = defineEmits<{
  sortChange: [payload: { prop: string | null, order: string | null }]
  toggleSelect: [id: number]
  toggleSelectAll: []
  edit: [id: number]
  delete: [row: Article]
}>()

const allSelected = computed(
  () => props.articles.length > 0 && props.selectedIds.length === props.articles.length,
)
const someSelected = computed(() => props.selectedIds.length > 0 && !allSelected.value)

/** el-table 的 sort-change 载荷比我们关心的字段更多，这里只转发需要的两项 */
function onSortChange(payload: { prop: string | null, order: string | null }) {
  emit('sortChange', payload)
}
</script>

<template>
  <div v-loading="loading" class="hidden overflow-x-auto md:block">
    <el-table
      :data="articles"
      row-key="id"
      border
      stripe
      :default-sort="{ prop: 'publish_time', order: 'descending' }"
      @sort-change="onSortChange"
    >
      <el-table-column width="44">
        <template #header>
          <el-checkbox
            :model-value="allSelected"
            :indeterminate="someSelected"
            @change="emit('toggleSelectAll')"
          />
        </template>
        <template #default="{ row }: { row: any }">
          <el-checkbox
            :model-value="selectedIds.includes(row.id)"
            @change="emit('toggleSelect', row.id)"
          />
        </template>
      </el-table-column>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="title" label="标题" min-width="180" />
      <el-table-column label="分类" width="120">
        <template #default="{ row }: { row: any }">
          {{ row.category?.name ?? '—' }}
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }: { row: any }">
          <el-tag :type="row.is_published ? 'success' : 'info'" size="small">
            {{ row.is_published ? '已发布' : '草稿' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="publish_time" label="发布时间" width="180" sortable="custom">
        <template #default="{ row }: { row: any }">
          {{ formatDateTime(row.publish_time) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="140">
        <template #default="{ row }: { row: any }">
          <el-button link type="primary" @click="emit('edit', row.id)">编辑</el-button>
          <el-button link type="danger" @click="emit('delete', row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>