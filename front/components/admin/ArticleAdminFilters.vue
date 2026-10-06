<script setup lang="ts">
/**
 * 文章管理页的筛选行（FE-09 从 `pages/administrator/articles/index.vue` 拆出）。
 * 筛选值由页面持有（v-model），本组件只负责渲染与"什么时候该重新拉取"（change/enter）。
 */
import type { Category } from '~/types/api'

defineProps<{ categories: Category[] }>()

const emit = defineEmits<{
  /** 下拉变化：由页面决定是回第 1 页还是直接刷新 */
  change: []
  /** 输入框回车 */
  search: []
}>()

const keyword = defineModel<string>('keyword', { required: true })
const categorySlug = defineModel<string>('categorySlug', { required: true })
const status = defineModel<string>('status', { required: true })
const sortOrder = defineModel<'asc' | 'desc'>('sortOrder', { required: true })
</script>

<template>
  <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
    <el-input v-model="keyword" placeholder="按标题搜索…" clearable @keyup.enter="emit('search')" />
    <el-select
      v-model="categorySlug"
      class="w-full"
      placeholder="按分类搜索"
      clearable
      @change="emit('change')"
    >
      <el-option v-for="c in categories" :key="c.id" :label="c.name" :value="c.slug" />
    </el-select>
    <el-select
      v-model="status"
      class="w-full"
      placeholder="按状态搜索"
      clearable
      @change="emit('change')"
    >
      <el-option label="已发布" value="true" />
      <el-option label="草稿" value="false" />
    </el-select>
    <!-- 移动端无表头，排序在此控制；桌面端用「发布时间」列表头排序 -->
    <el-select v-model="sortOrder" class="w-full md:hidden" @change="emit('change')">
      <el-option label="发布时间：最新在前" value="desc" />
      <el-option label="发布时间：最早在前" value="asc" />
    </el-select>
  </div>
</template>