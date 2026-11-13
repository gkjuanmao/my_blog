<script setup lang="ts">
import type { ArticleDetail } from '~/types/api'

const route = useRoute()
// 必须是 computed：同路由仅参数变化时组件实例复用、setup 不会重跑，
// 常量 slug 会让 useAsyncData 的 key 恒为旧值，导致切换文章显示上一篇。
const slug = computed(() => route.params.slug as string)

const coverError = ref(false)

// 本页导航与首页同款（fixed 透明浮层），顶态需要浅色画布配色：
// 挂一个 html 作用域类供 home-cover.css 的顶态覆盖命中（与 .tl-page 并列）。
// ⚠️ 皮肤类由 layout 的 useHead 合并进来，这里只加自己的类，不要整段覆盖 htmlAttrs。
useHead({
  htmlAttrs: { class: 'art-page' },
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
  <article v-if="article" class="cv-article">
    <header class="cv-article__head">
      <p class="cv-article__eyebrow">
        <span v-if="article.category" lang="en">{{ article.category.name }}</span>
        <template v-if="article.category"> / </template>
        <span lang="en">TRAVEL JOURNAL</span>
      </p>
      <h1 class="cv-article__title">{{ article.title }}</h1>
      <div class="cv-article__meta">
        <time :datetime="article.publish_time">{{ formatDate(article.publish_time) }}</time>
        <span v-if="article.location" class="cv-article__meta-item">{{ article.location }}</span>
        <span v-if="article.views" class="cv-article__meta-item">{{ article.views }} 次阅读</span>
      </div>
    </header>

    <!-- 封面：宽幅裁切，圆角与首页卡片一致 -->
    <figure class="cv-article__cover" :class="{ 'is-failed': !article.cover_image_url || coverError }">
      <img
        v-if="article.cover_image_url && !coverError"
        :src="article.cover_image_url"
        :alt="article.title"
        width="1600"
        height="900"
        fetchpriority="high"
        decoding="async"
        @error="coverError = true"
      >
      <figcaption v-if="article.summary" class="cv-article__lede">{{ article.summary }}</figcaption>
    </figure>

    <!-- 正文：服务端渲染 + 消毒后的 HTML（nh3 白名单，见 AGENTS.md） -->
    <!-- eslint-disable-next-line vue/no-v-html -->
    <div v-if="hasContent" class="md-body cv-article__body" v-html="article.content_html" />

    <!-- 存量文章（无正文）回退：只给附件下载入口，不再做 PDF 在线预览 -->
    <div v-else-if="!article.file_url" class="cv-state">
      该文章暂无正文
    </div>
    <div v-else class="cv-state">
      该文章以附件形式提供，请下载后查看。
    </div>

    <div v-if="article.file_url" class="cv-article__attachment">
      <a
        :href="article.file_url"
        :download="article.file_name"
        target="_blank"
        rel="noopener"
        class="cv-btn cv-btn--primary"
      >
        下载附件（{{ article.file_name }}）
      </a>
    </div>

    <footer class="cv-article__foot">
      <NuxtLink to="/" class="cv-article__back">← 返回首页</NuxtLink>
      <NuxtLink to="/timeline" class="cv-article__back">按时间轴浏览 →</NuxtLink>
    </footer>
  </article>

  <div v-else-if="pending" class="cv-state">加载中…</div>
  <div v-else class="cv-state">
    <p>{{ fetchError ? '文章不存在或已下架' : '文章不存在' }}</p>
    <NuxtLink to="/" class="cv-article__back">返回首页</NuxtLink>
  </div>
</template>
