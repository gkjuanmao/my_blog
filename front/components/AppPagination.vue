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

const isMobile = ref(false)
let mql: MediaQueryList | null = null
const onBreakpointChange = (e: MediaQueryListEvent) => {
  isMobile.value = e.matches
}

onMounted(() => {
  mql = window.matchMedia('(max-width: 639px)')
  isMobile.value = mql.matches
  mql.addEventListener('change', onBreakpointChange)
})

onBeforeUnmount(() => {
  mql?.removeEventListener('change', onBreakpointChange)
})

const effectiveLayout = computed(() => (isMobile.value ? 'prev, pager, next' : props.layout))

watch(pageSize, () => {
  page.value = 1
})
</script>

<template>
  <el-pagination
    v-model:current-page="page"
    v-model:page-size="pageSize"
    :total="total"
    :layout="effectiveLayout"
    :background="background"
    :page-sizes="pageSizes"
    :small="isMobile"
    :pager-count="isMobile ? 5 : 7"
  />
</template>
