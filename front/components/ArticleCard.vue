<script setup lang="ts">
import type { Article } from '~/types/api'

const props = defineProps<{ article: Article }>()

const dateFormatter = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  year: 'numeric',
  month: 'long',
  day: 'numeric',
})

const coverError = ref(false)

function formatDate(iso: string): string {
  return dateFormatter.format(new Date(iso))
}

function handleClick() {
  navigateTo(`/article/${props.article.slug}`)
}
</script>

<template>
  <article
    class="group cursor-pointer overflow-hidden rounded-2xl border border-stone-200 bg-white shadow-sm transition-all hover:-translate-y-1 hover:shadow-md dark:border-stone-700 dark:bg-stone-900"
    @click="handleClick"
  >
    <div class="aspect-video w-full overflow-hidden bg-stone-100 dark:bg-stone-800">
      <img
        v-if="article.cover_image_url && !coverError"
        :src="article.cover_image_url"
        :alt="article.title"
        class="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
        loading="lazy"
        @error="coverError = true"
      />
      <div v-else class="flex h-full w-full items-center justify-center text-4xl text-stone-300 dark:text-stone-600">✈</div>
    </div>

    <div class="p-5">
      <div class="mb-2 flex flex-wrap items-center gap-2">
        <el-tag v-if="article.category" type="warning" effect="light" size="small">
          {{ article.category.name }}
        </el-tag>
        <el-tag v-for="tag in article.tags.slice(0, 3)" :key="tag.id" size="small" effect="plain">
          #{{ tag.name }}
        </el-tag>
      </div>
      <h2 class="mb-2 text-xl font-semibold text-stone-900 group-hover:text-brand-600 dark:text-stone-100 dark:group-hover:text-amber-400">
        {{ article.title }}
      </h2>
      <p class="mb-3 line-clamp-2 text-sm text-stone-500 dark:text-stone-400">{{ article.summary }}</p>
      <time class="text-xs text-stone-400 dark:text-stone-500">{{ formatDate(article.publish_time) }}</time>
    </div>
  </article>
</template>
