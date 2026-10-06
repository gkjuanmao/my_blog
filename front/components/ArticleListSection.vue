<script setup lang="ts">
/**
 * 公开列表页的「首屏加载 / 出错 / 网格 / 分页」四态区（FE-11）。
 *
 * 首页、分类页、标签页原本复制了同一段模板（差别只有空态文案），这里收敛成一处。
 * 搜索页不适用：它的三态语义不同（未搜索 / 搜索中 / 无结果），故只用 `ArticleGrid`。
 *
 * 分页状态用 v-model:page / v-model:page-size 与页面（URL query）双向同步。
 */
import type { Article } from '~/types/api'

withDefaults(
  defineProps<{
    articles: Article[]
    total: number
    loading: boolean
    errorMsg: string
    /** 无内容时的提示 */
    emptyText: string
    /** 首屏加载提示 */
    loadingText?: string
  }>(),
  { loadingText: '加载中…' },
)

const page = defineModel<number>('page', { required: true })
const pageSize = defineModel<number>('pageSize', { required: true })
</script>

<template>
  <div
    v-if="loading && articles.length === 0"
    class="py-16 text-center text-sm text-stone-400"
  >
    {{ loadingText }}
  </div>
  <div v-else-if="errorMsg" class="py-16 text-center text-sm text-red-500">{{ errorMsg }}</div>
  <template v-else>
    <ArticleGrid :articles="articles" :empty-text="emptyText" />
    <div v-if="total > 0" class="mt-8 flex justify-center">
      <AppPagination
        v-model:page="page"
        v-model:page-size="pageSize"
        :total="total"
        :reset-page-on-size-change="false"
      />
    </div>
  </template>
</template>