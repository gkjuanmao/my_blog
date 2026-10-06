<script setup lang="ts">
/**
 * 文章卡片网格 + 空态提示（FE-11）。4 个公开列表页共用；无内容时由 `emptyText` 决定提示。
 */
import type { Article } from '~/types/api'

defineProps<{
  articles: Article[]
  /** 无内容时的提示；不传则不渲染占位 */
  emptyText?: string
}>()
</script>

<template>
  <div v-if="articles.length > 0" class="grid grid-cols-1 gap-6 sm:grid-cols-2">
    <ArticleCard v-for="article in articles" :key="article.id" :article="article" />
  </div>
  <div v-else-if="emptyText" class="py-16 text-center text-sm text-stone-400">{{ emptyText }}</div>
</template>