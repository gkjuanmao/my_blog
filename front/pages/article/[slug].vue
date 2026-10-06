<script setup lang="ts">
import type { ArticleDetail } from '~/types/api'

const route = useRoute()
// 必须是 computed：同路由仅参数变化时组件实例复用、setup 不会重跑，
// 常量 slug 会让 useAsyncData 的 key 恒为旧值，导致切换文章显示上一篇。
const slug = computed(() => route.params.slug as string)

const coverError = ref(false)

const dateFormatter = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  year: 'numeric',
  month: 'long',
  day: 'numeric',
})

const { data: article, pending, error: fetchError } = await useAsyncData<ArticleDetail>(
  () => `article-${slug.value}`,
  () => useApi().get<ArticleDetail>(`/articles/${slug.value}/`).then((res) => res.data),
  { watch: [slug] },
)

// 正文由服务端渲染并消毒（content_html），前端只做展示，不再引入 markdown 依赖
const hasContent = computed(() => Boolean(article.value?.content_html?.trim()))

// ------------------------------------------------------------------ SEO
const { site: siteConfig } = useAppConfig()
const origin = useRequestURL().origin
const ogImage = computed(() =>
  article.value?.cover_image_url
    ? new URL(article.value.cover_image_url, origin).toString()
    : undefined,
)

useSeoMeta({
  title: () => article.value?.title ?? '文章',
  description: () =>
    article.value?.summary ||
    `「${article.value?.title ?? siteConfig.name}」— ${siteConfig.name}`,
  ogTitle: () => article.value?.title ?? siteConfig.name,
  ogDescription: () => article.value?.summary || undefined,
  ogType: 'article',
  ogImage: () => ogImage.value,
  articlePublishedTime: () => article.value?.publish_time ?? undefined,
  twitterCard: 'summary_large_image',
})

useHead(() => ({
  script: article.value
    ? [
        {
          type: 'application/ld+json',
          innerHTML: JSON.stringify({
            '@context': 'https://schema.org',
            '@type': 'BlogPosting',
            headline: article.value.title,
            description: article.value.summary || undefined,
            image: ogImage.value,
            datePublished: article.value.publish_time,
            author: { '@type': 'Person', name: article.value.author },
          }),
        },
      ]
    : [],
}))
</script>

<template>
  <article v-if="article" class="space-y-6">
    <div data-skin="surface" class="overflow-hidden rounded-2xl bg-stone-100 dark:bg-stone-800">
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
      <h1 class="text-2xl font-serif font-bold text-stone-900 dark:text-stone-100 sm:text-3xl">{{ article.title }}</h1>
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

    <!-- 正文：服务端渲染 + 消毒后的 HTML -->
    <div v-if="hasContent" class="md-body" v-html="article.content_html" />

    <!-- 存量文章（无正文）回退：只给附件下载入口，不再做 PDF 在线预览 -->
    <div
      v-else-if="!article.file_url"
      class="rounded-xl border border-dashed border-stone-300 py-12 text-center text-sm text-stone-400 dark:border-stone-700"
    >
      该文章暂无正文
    </div>
    <div
      v-else
      class="rounded-xl border border-dashed border-stone-300 py-12 text-center text-sm text-stone-500 dark:border-stone-700 dark:text-stone-400"
    >
      该文章以附件形式提供，请下载后查看。
    </div>

    <div v-if="article.file_url" class="flex justify-center">
      <a
        :href="article.file_url"
        :download="article.file_name"
        target="_blank"
        rel="noopener"
        data-skin="button"
        class="rounded-lg bg-brand-600 px-6 py-2.5 text-sm font-medium text-white transition-colors hover:bg-brand-700 dark:bg-amber-600 dark:hover:bg-amber-500"
      >
        下载附件（{{ article.file_name }}）
      </a>
    </div>
  </article>

  <div v-else-if="pending" class="py-16 text-center text-sm text-stone-400">加载中…</div>
  <div v-else class="py-16 text-center">
    <p class="mb-4 text-sm text-red-500">{{ fetchError ? '文章不存在或已下架' : '文章不存在' }}</p>
    <NuxtLink to="/" class="text-sm text-brand-600 hover:underline dark:text-amber-400">返回首页</NuxtLink>
  </div>
</template>