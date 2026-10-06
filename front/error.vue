<script setup lang="ts">
import type { NuxtError } from '#app'

const props = defineProps<{ error: NuxtError }>()

const isNotFound = computed(() => props.error?.statusCode === 404)

function goHome() {
  clearError({ redirect: '/' })
}
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-paper-light px-4 text-ink-light dark:bg-stone-900 dark:text-stone-100">
    <div class="w-full max-w-md rounded-2xl border border-stone-200 bg-white p-8 text-center shadow-sm dark:border-stone-700 dark:bg-stone-900">
      <div class="font-serif text-5xl font-bold text-brand-600 dark:text-amber-500">
        {{ error?.statusCode ?? 500 }}
      </div>
      <p class="mt-4 text-sm text-stone-600 dark:text-stone-300">
        {{ isNotFound ? '页面不存在或已下架' : '页面出错了，请稍后重试' }}
      </p>
      <p v-if="error?.statusMessage && !isNotFound" class="mt-2 text-xs text-stone-400">
        {{ error.statusMessage }}
      </p>
      <button
        type="button"
        class="mt-6 rounded-lg bg-brand-600 px-6 py-2.5 text-sm font-medium text-white transition-colors hover:bg-brand-700 dark:bg-amber-600 dark:hover:bg-amber-500"
        @click="goHome"
      >
        返回首页
      </button>
    </div>
  </div>
</template>