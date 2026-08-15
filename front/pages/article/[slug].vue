<script setup lang="ts">
import type { ArticleDetail } from '~/types/api'

const route = useRoute()
const slug = route.params.slug as string

const article = ref<ArticleDetail | null>(null)
const loading = ref(true)
const errorMsg = ref('')
const coverError = ref(false)

const dateFormatter = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  year: 'numeric',
  month: 'long',
  day: 'numeric',
})

async function fetchArticle() {
  loading.value = true
  errorMsg.value = ''
  try {
    const { data } = await useApi().get<ArticleDetail>(`/articles/${slug}/`)
    article.value = data
  } catch (e: any) {
    errorMsg.value = '文章不存在或已下架'
  } finally {
    loading.value = false
  }
}

await fetchArticle()
</script>

<template>
  <article v-if="article" class="space-y-6">
    <div class="overflow-hidden rounded-2xl bg-stone-100 dark:bg-stone-800">
      <img
        v-if="article.cover_image_url && !coverError"
        :src="article.cover_image_url"
        :alt="article.title"
        class="max-h-96 w-full object-cover"
        @error="coverError = true"
      />
      <div v-else class="flex h-56 w-full items-center justify-center text-6xl text-stone-300 dark:text-stone-600">✈</div>
    </div>

    <header class="space-y-2">
      <h1 class="text-3xl font-serif font-bold text-stone-900 dark:text-stone-100">{{ article.title }}</h1>
      <div class="flex flex-wrap items-center gap-3 text-sm text-stone-500 dark:text-stone-400">
        <time>{{ dateFormatter.format(new Date(article.publish_time)) }}</time>
        <span v-if="article.location">· {{ article.location }}</span>
        <el-tag v-if="article.category" type="warning" effect="light" size="small">
          {{ article.category.name }}
        </el-tag>
        <span>· {{ article.views }} 次阅读</span>
      </div>
    </header>

    <p v-if="article.summary" class="text-stone-600 dark:text-stone-300">{{ article.summary }}</p>

    <div v-if="article.file_url" class="space-y-4">
      <PdfViewer :pdf-url="article.file_url" />
      <div class="flex justify-center">
        <a
          :href="article.file_url"
          :download="article.file_name"
          target="_blank"
          rel="noopener"
          class="rounded-lg bg-brand-600 px-6 py-2.5 text-sm font-medium text-white transition-colors hover:bg-brand-700 dark:bg-amber-600 dark:hover:bg-amber-500"
        >
          下载附件（{{ article.file_name }}）
        </a>
      </div>
    </div>
    <div v-else class="rounded-xl border border-dashed border-stone-300 py-12 text-center text-sm text-stone-400 dark:border-stone-700">
      该文章暂无附件
    </div>
  </article>

  <div v-else-if="loading" class="py-16 text-center text-sm text-stone-400">加载中…</div>
  <div v-else class="py-16 text-center">
    <p class="mb-4 text-sm text-red-500">{{ errorMsg }}</p>
    <NuxtLink to="/" class="text-sm text-brand-600 hover:underline dark:text-amber-400">返回首页</NuxtLink>
  </div>
</template>
