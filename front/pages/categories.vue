<script setup lang="ts">
import type { Category } from '~/types/api'

const categories = ref<Category[]>([])
const loading = ref(true)
const errorMsg = ref('')

useSeoMeta({ title: '分类', description: '按分类浏览全部游记' })

try {
  const { data } = await useApi().get<Category[]>('/categories/')
  categories.value = data
} catch (e) {
  errorMsg.value = errorMessage(e, '加载失败')
} finally {
  loading.value = false
}
</script>

<template>
  <div class="space-y-6">
    <h1 class="text-2xl font-serif font-bold text-stone-900 dark:text-stone-100">全部分类</h1>

    <div v-if="loading" class="py-16 text-center text-sm text-stone-400">加载中…</div>
    <div v-else-if="errorMsg" class="py-16 text-center text-sm text-red-500">{{ errorMsg }}</div>
    <div v-else-if="categories.length === 0" class="py-16 text-center text-sm text-stone-400">暂无分类</div>
    <div v-else class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <NuxtLink
        v-for="category in categories"
        :key="category.id"
        :to="`/category/${category.slug}`"
        data-skin="card-link"
        class="rounded-2xl border border-stone-200 bg-white p-5 transition-all hover:-translate-y-1 hover:shadow-md dark:border-stone-700 dark:bg-stone-900"
      >
        <h2 class="mb-1 text-lg font-semibold text-brand-600 dark:text-amber-400">{{ category.name }}</h2>
        <p v-if="category.description" class="text-sm text-stone-500 dark:text-stone-400">{{ category.description }}</p>
      </NuxtLink>
    </div>
  </div>
</template>
