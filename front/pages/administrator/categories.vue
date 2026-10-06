<script setup lang="ts">
import type { CrudColumn, CrudField } from '~/composables/useCrudTable'
import { useCrudTable } from '~/composables/useCrudTable'

definePageMeta({ layout: 'admin' })

const columns: CrudColumn[] = [
  { prop: 'id', label: 'ID', width: '70' },
  { prop: 'name', label: '名称' },
  { prop: 'slug', label: 'Slug' },
  { prop: 'description', label: '描述' },
]
const fields: CrudField[] = [
  { key: 'name', label: '名称', placeholder: '请输入名称' },
  { key: 'slug', label: 'Slug（留空自动生成）', placeholder: '如 travel' },
  { key: 'description', label: '描述', placeholder: '可选' },
]

const { list, loading, fetchList, submit, remove } = useCrudTable({
  listUrl: '/categories/',
  baseUrl: '/admin/categories',
})

onMounted(fetchList)
</script>

<template>
  <ResourceCrudTable
    title="分类管理"
    label="分类"
    :list="list"
    :loading="loading"
    :columns="columns"
    :fields="fields"
    :submit="submit"
    :remove="remove"
    show-description
    @changed="fetchList"
  />
</template>