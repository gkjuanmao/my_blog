<script setup lang="ts">
import type { ApiResponse, Category } from '~/types/api'

const categories = ref<Category[]>([])
const loading = ref(true)
const errorMsg = ref('')

onMounted(async () => {
  try {
    const { data } = await useApi().get<Category[]>('/categories/')
    categories.value = data
  } catch (e: any) {
    errorMsg.value = e?.message ?? '加载失败'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <main class="mx-auto max-w-4xl px-6 py-12">
    <h1 class="mb-8 text-3xl font-bold text-brand-600">旅行游记</h1>
    <div v-if="loading" class="text-sm text-gray-400">加载中…</div>
    <div v-else-if="errorMsg" class="text-sm text-red-500">{{ errorMsg }}</div>
    <div v-else class="flex flex-wrap gap-2">
      <el-tag v-for="c in categories" :key="c.id" type="warning" effect="light">
        {{ c.name }}
      </el-tag>
    </div>
  </main>
</template>
