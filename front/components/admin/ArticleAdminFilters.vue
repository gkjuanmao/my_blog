<script setup lang="ts">
/**
 * 文章管理页的筛选行：工具带里的一排行内控件（搜索 / 栏目 / 作者 / 状态 ｜ 排序）。
 * 筛选值由页面持有（v-model），本组件只负责渲染与「什么时候该重新拉取」。
 *
 * 三个下拉都走 AdminSelect（自绘列表）：原生 select 的弹层是系统样式，
 * 且 option 里塞不下「作者（36）」这种右侧数字。
 */
import type { AdminAuthor, Category } from '~/types/api'
import type { SelectOption } from '~/types/admin'

const props = defineProps<{
  categories: Category[]
  /** 作者选项：来自 /admin/articles/authors/（含草稿口径）；非 staff 时页面传空数组 */
  authors: AdminAuthor[]
}>()

const emit = defineEmits<{
  /** 下拉/页签变化：由页面决定是回第 1 页还是直接刷新 */
  change: []
  /** 输入框回车或点「搜索」 */
  search: []
}>()

const keyword = defineModel<string>('keyword', { required: true })
const categorySlug = defineModel<string>('categorySlug', { required: true })
const authorId = defineModel<string>('authorId', { required: true })
const status = defineModel<string>('status', { required: true })
const sortOrder = defineModel<'asc' | 'desc'>('sortOrder', { required: true })

const statusOptions = [
  { value: '', label: '全部' },
  { value: 'true', label: '已发布' },
  { value: 'false', label: '草稿' },
]

const categoryOptions = computed<SelectOption[]>(() => [
  { value: '', label: '全部栏目', muted: true },
  ...props.categories.map(c => ({ value: c.slug, label: c.name })),
])

const authorOptions = computed<SelectOption[]>(() => [
  { value: '', label: '全部作者', muted: true },
  ...props.authors.map(a => ({
    value: String(a.id),
    label: a.username,
    hint: `${a.article_count}`,
  })),
])

const sortOptions: SelectOption[] = [
  { value: 'desc', label: '发布时间 · 新 → 旧' },
  { value: 'asc', label: '发布时间 · 旧 → 新' },
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

    <AdminSelect
      v-model="categorySlug"
      label="按栏目筛选"
      :options="categoryOptions"
      style="min-width: 126px"
      @change="emit('change')"
    />

    <!-- 只有一位作者时整块不渲染：那时「全部作者」与「某人的」是同一批稿 -->
    <AdminSelect
      v-if="authors.length > 1"
      v-model="authorId"
      label="按作者筛选"
      :options="authorOptions"
      style="min-width: 138px"
      @change="emit('change')"
    />

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

    <span class="ad-toolbar__div" aria-hidden="true" />

    <AdminSelect
      v-model="sortOrder"
      label="排序方式"
      :options="sortOptions"
      style="min-width: 168px"
      @change="emit('change')"
    />

    <button class="ad-btn ad-btn--ghost ad-btn--sm" type="button" @click="emit('search')">
      搜索
    </button>

    <span class="ad-toolbar__spacer" />

    <slot name="right" />
  </div>
</template>
