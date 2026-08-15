<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    total: number
    layout?: string
    background?: boolean
    pageSizes?: number[]
  }>(),
  {
    layout: 'total, sizes, prev, pager, next',
    background: true,
    pageSizes: () => [10, 20, 50],
  },
)

const page = defineModel<number>('page', { default: 1 })
const pageSize = defineModel<number>('pageSize', { default: 10 })

watch(pageSize, () => {
  page.value = 1
})
</script>

<template>
  <el-pagination
    v-model:current-page="page"
    v-model:page-size="pageSize"
    :total="total"
    :layout="layout"
    :background="background"
    :page-sizes="pageSizes"
  />
</template>
