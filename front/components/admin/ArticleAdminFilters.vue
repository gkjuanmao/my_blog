<script setup lang="ts">
/**
 * 文章管理页的筛选行：工具带里的一排行内控件（搜索 / 栏目 / 状态 / 排序）。
 * 筛选值由页面持有（v-model），本组件只负责渲染与「什么时候该重新拉取」。
 */
import type { Category } from '~/types/api'

defineProps<{ categories: Category[] }>()

const emit = defineEmits<{
  /** 下拉/页签变化：由页面决定是回第 1 页还是直接刷新 */
  change: []
  /** 输入框回车或点「搜索」 */
  search: []
}>()

const keyword = defineModel<string>('keyword', { required: true })
const categorySlug = defineModel<string>('categorySlug', { required: true })
const status = defineModel<string>('status', { required: true })
const sortOrder = defineModel<'asc' | 'desc'>('sortOrder', { required: true })

const statusOptions = [
  { value: '', label: '全部' },
  { value: 'true', label: '已发布' },
  { value: 'false', label: '草稿' },
]

function pickStatus(value: string) {
  if (status.value === value) return
  status.value = value
  emit('change')
}
</script>

<template>
  <div class="ad-toolbar">
    <label class="ad-tool" style="width: 232px">
      <AdminIcon name="search" :size="14" />
      <input
        v-model="keyword"
        type="search"
        placeholder="搜标题或 slug…"
        autocomplete="off"
        aria-label="关键词"
        @keyup.enter="emit('search')"
      >
    </label>

    <label class="ad-tool ad-tool--sel" style="min-width: 126px">
      <span class="ad-sr">栏目</span>
      <select v-model="categorySlug" @change="emit('change')">
        <option value="">全部栏目</option>
        <option v-for="c in categories" :key="c.id" :value="c.slug">{{ c.name }}</option>
      </select>
    </label>

    <div class="ad-segs" role="group" aria-label="按发布状态筛选">
      <button
        v-for="option in statusOptions"
        :key="option.value"
        class="ad-seg"
        type="button"
        :aria-pressed="status === option.value"
        @click="pickStatus(option.value)"
      >
        {{ option.label }}
      </button>
    </div>

    <label class="ad-tool ad-tool--sel" style="min-width: 168px">
      <span class="ad-sr">排序</span>
      <select v-model="sortOrder" @change="emit('change')">
        <option value="desc">发布时间 · 新 → 旧</option>
        <option value="asc">发布时间 · 旧 → 新</option>
      </select>
    </label>

    <button class="ad-btn ad-btn--ghost ad-btn--sm" type="button" @click="emit('search')">
      搜索
    </button>

    <span class="ad-toolbar__spacer" />

    <slot name="right" />
  </div>
</template>
