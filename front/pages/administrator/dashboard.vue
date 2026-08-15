<script setup lang="ts">
import type { Category, PaginatedResponse } from '~/types/api'

definePageMeta({ layout: 'admin' })

const totalArticles = ref(0)
const publishedArticles = ref(0)
const totalCategories = ref(0)
const loading = ref(true)
const errorMsg = ref('')

onMounted(async () => {
  try {
    const [all, published, cats] = await Promise.all([
      useApi().get<PaginatedResponse<unknown>>('/admin/articles/', { page_size: 1 }),
      useApi().get<PaginatedResponse<unknown>>('/admin/articles/', { page_size: 1, is_published: true }),
      useApi().get<Category[]>('/categories/'),
    ])
    totalArticles.value = all.data.total
    publishedArticles.value = published.data.total
    totalCategories.value = cats.data.length
  } catch (e: any) {
    errorMsg.value = e?.data?.message ?? '加载失败'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div>
    <h1 class="text-xl font-semibold">仪表盘</h1>
    <div v-if="loading" class="py-12 text-center text-sm text-stone-400">加载中…</div>
    <div v-else-if="errorMsg" class="py-12 text-center text-sm text-red-500">{{ errorMsg }}</div>
    <div v-else class="grid grid-cols-1 gap-6 sm:grid-cols-3">
      <el-card shadow="hover">
        <div class="text-sm text-stone-500">总文章数</div>
        <div class="mt-2 text-3xl font-bold text-brand-600 dark:text-amber-400">{{ totalArticles }}</div>
      </el-card>
      <el-card shadow="hover">
        <div class="text-sm text-stone-500">已发布文章</div>
        <div class="mt-2 text-3xl font-bold text-brand-600 dark:text-amber-400">{{ publishedArticles }}</div>
      </el-card>
      <el-card shadow="hover">
        <div class="text-sm text-stone-500">总分类数</div>
        <div class="mt-2 text-3xl font-bold text-brand-600 dark:text-amber-400">{{ totalCategories }}</div>
      </el-card>
    </div>
  </div>
</template>
