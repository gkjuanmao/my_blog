<script setup lang="ts">
import type { CrudColumn, CrudField } from '~/composables/useCrudTable'
import { useCrudTable } from '~/composables/useCrudTable'

definePageMeta({ layout: 'admin' })

const columns: CrudColumn[] = [
  { prop: 'id', label: 'ID', width: '70' },
  { prop: 'name', label: '名称' },
  { prop: 'slug', label: 'Slug' },
]
const fields: CrudField[] = [
  { key: 'name', label: '名称', placeholder: '请输入名称' },
  { key: 'slug', label: 'Slug（留空自动生成）', placeholder: '如 travel' },
]

const { list, loading, fetchList, submit, remove } = useCrudTable({
  listUrl: '/tags/',
  baseUrl: '/admin/tags',
})

onMounted(fetchList)
</script>

<template>
  <ResourceCrudTable
    title="标签管理"
    label="标签"
    :list="list"
    :loading="loading"
    :columns="columns"
    :fields="fields"
    :submit="submit"
    :remove="remove"
    name-prefix="# "
    @changed="fetchList"
  />
</template>