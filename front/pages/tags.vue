<script setup lang="ts">
import type { Tag } from '~/types/api'

const tags = ref<Tag[]>([])
const loading = ref(true)
const errorMsg = ref('')

useSeoMeta({ title: '标签', description: '按标签浏览全部游记' })

try {
  const { data } = await useApi().get<Tag[]>('/tags/')
  tags.value = data
} catch (e: any) {
  errorMsg.value = e?.message ?? '加载失败'
} finally {
  loading.value = false
}
</script>

<template>
  <div class="space-y-6">
    <h1 class="text-2xl font-serif font-bold text-stone-900 dark:text-stone-100">全部标签</h1>

    <div v-if="loading" class="py-16 text-center text-sm text-stone-400">加载中…</div>
    <div v-else-if="errorMsg" class="py-16 text-center text-sm text-red-500">{{ errorMsg }}</div>
    <div v-else-if="tags.length === 0" class="py-16 text-center text-sm text-stone-400">暂无标签</div>
    <div v-else class="flex flex-wrap gap-3">
      <NuxtLink
        v-for="tag in tags"
        :key="tag.id"
        :to="`/tag/${tag.slug}`"
        class="rounded-full border border-stone-300 px-4 py-1.5 text-sm text-stone-600 transition-colors hover:border-brand-500 hover:text-brand-600 dark:border-stone-600 dark:text-stone-300 dark:hover:border-amber-500 dark:hover:text-amber-400"
      >
        #{{ tag.name }}
      </NuxtLink>
    </div>
  </div>
</template>
