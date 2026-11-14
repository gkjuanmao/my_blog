<script setup lang="ts">
/**
 * 首页卡片（三种版式：精选 / 标准 / 宽卡）。
 *
 * 可达性要点（02-ux-spec.md §3）：
 *  - 整卡是**一个 `<a>`**：支持右键新标签、中键、拖拽、状态栏显示 URL、读屏「链接」；
 *  - 卡内零第二个交互元素；
 *  - 卡内 `<img alt="">`（M3：整卡可访达名称已含标题，重复 alt 会被念两遍并破坏 2.5.3）；
 *  - 序号 / underline / 触屏角标 / 所有遮罩层 `aria-hidden`；
 *  - 日期用 `<time datetime>` + 视觉截断 + `sr-only` 全文（不用 aria-label：generic 角色上被禁用）。
 */
import type { Article } from '~/types/api'
import { shortPlace } from '~/utils/place'

const props = defineProps<{
  article: Article
  variant: 'featured' | 'std' | 'wide'
  /** 全局序号（已补零两位），不是页内序号 */
  index: string
  total: number
  page: number
  /** 是否最后一页：宽卡角标在「本期终 / 本页终」之间切换 */
  isLastPage: boolean
  /** 印章字（站点名首字） */
  sealChar: string
  /** 是否显示作者名：只在「按作者筛选」生效时显示，默认视图保持信息密度不变 */
  showAuthor?: boolean
}>()

const failed = ref(false)
const coverUrl = computed(() => props.article.cover_image_url ?? '')
const showCover = computed(() => Boolean(coverUrl.value) && !failed.value)

watch(coverUrl, () => {
  failed.value = false
})

const href = computed(() => `/article/${props.article.slug}`)
const categoryName = computed(() => props.article.category?.name ?? '')
const authorName = computed(() => (props.showAuthor ? (props.article.author_name ?? '') : ''))
/** location 为空时必须整行不渲染（否则会多出 13px 行高，卡片高度不齐） */
const location = computed(() => shortPlace(props.article.location ?? ''))

const dateCompact = computed(() => formatDateCompact(props.article.publish_time))
const dateFull = computed(() => formatDate(props.article.publish_time))
/** 非法 ISO 串不渲染 datetime 属性，而不是输出一个坏值 */
const isoDatetime = computed(() => {
  const iso = props.article.publish_time
  return iso && !Number.isNaN(Date.parse(iso)) ? iso : undefined
})

/** views 只在 >0 时出现，千位收敛为 1.2k */
const viewsLabel = computed(() => {
  const views = props.article.views
  if (!views || views <= 0) return ''
  return `${views >= 1000 ? `${(views / 1000).toFixed(1)}k` : String(views)} 次阅读`
})

const featuredEyebrow = computed(() => (props.page === 1 ? '本期卷首' : '本页首篇'))
const finText = computed(() => (props.isLastPage ? '本期终' : '本页终'))
</script>

<template>
  <!-- 精选：12 列，左 40% 面板 + 右 60% 照片 -->
  <a v-if="variant === 'featured'" class="cv-feat" :href="href">
    <div class="cv-feat__inner">
      <div class="cv-feat__panel">
        <p class="cv-feat__eyebrow">
          <span lang="en">FEATURED</span> / {{ featuredEyebrow }}
        </p>
        <h3>{{ article.title }}</h3>
        <p v-if="location" class="cv-feat__route">{{ location }}</p>
        <p class="cv-feat__meta">
          <time :datetime="isoDatetime">
            <span aria-hidden="true">{{ dateCompact }}</span>
            <span class="sr-only">{{ dateFull }}</span>
          </time>
          <template v-if="categoryName"> · {{ categoryName }}</template>
          <template v-if="authorName"> · {{ authorName }}</template>
          <template v-if="viewsLabel"> · {{ viewsLabel }}</template>
        </p>
        <span class="cv-feat__seal" aria-hidden="true">{{ sealChar }}</span>
        <span class="cv-feat__readmore" aria-hidden="true">阅读全文 →</span>
        <span class="cv-feat__index" aria-hidden="true">{{ index }} / {{ total }}</span>
      </div>

      <div class="cv-feat__media" :class="{ 'is-failed': !showCover }">
        <img
          v-if="showCover"
          :src="coverUrl"
          alt=""
          width="1600"
          height="1000"
          loading="eager"
          fetchpriority="low"
          decoding="async"
          @error="failed = true"
        >
        <span class="cv-feat__scrim" aria-hidden="true"/>
        <span class="cv-feat__seam" aria-hidden="true"/>
      </div>
    </div>
  </a>

  <!-- 宽卡：12 列 4:1 -->
  <a v-else-if="variant === 'wide'" class="cv-wide" :href="href">
    <div class="cv-wide__media" :class="{ 'is-failed': !showCover }">
      <img
        v-if="showCover"
        :src="coverUrl"
        alt=""
        width="1600"
        height="400"
        loading="lazy"
        decoding="async"
        @error="failed = true"
      >
      <span class="cv-wide__scrim" aria-hidden="true"/>
      <span class="cv-wide__fin" aria-hidden="true">{{ finText }}</span>
    </div>
    <div class="cv-wide__text">
      <h3>{{ article.title }}</h3>
      <span class="cv-card__underline" aria-hidden="true"/>
      <p class="cv-card__foot">
        <span v-if="location" class="cv-card__route">{{ location }}</span>
        <time class="cv-card__date" :datetime="isoDatetime">
          <span aria-hidden="true">{{ dateCompact }}</span>
          <span class="sr-only">{{ dateFull }}</span>
        </time>
        <span v-if="authorName" class="cv-card__author">{{ authorName }}</span>
        <span class="cv-wide__index" aria-hidden="true">· {{ index }} / {{ total }}</span>
      </p>
    </div>
  </a>

  <!-- 标准卡：6 列，16:10 图 + 图上文字 -->
  <a v-else class="cv-card" :href="href">
    <div class="cv-card__media" :class="{ 'is-failed': !showCover }">
      <img
        v-if="showCover"
        :src="coverUrl"
        alt=""
        width="1600"
        height="1000"
        loading="lazy"
        decoding="async"
        @error="failed = true"
      >
      <span class="cv-card__tone" aria-hidden="true"/>
      <span class="cv-card__top" aria-hidden="true"/>
      <span class="cv-card__scrim" aria-hidden="true"/>
    </div>
    <div class="cv-card__text">
      <span v-if="categoryName" class="cv-card__chip">{{ categoryName }}</span>
      <span class="cv-card__num" aria-hidden="true">{{ index }}</span>
      <h3>{{ article.title }}</h3>
      <span class="cv-card__underline" aria-hidden="true"/>
      <p class="cv-card__foot">
        <span v-if="location" class="cv-card__route">{{ location }}</span>
        <time class="cv-card__date" :datetime="isoDatetime">
          <span aria-hidden="true">{{ dateCompact }}</span>
          <span class="sr-only">{{ dateFull }}</span>
        </time>
        <span v-if="authorName" class="cv-card__author">{{ authorName }}</span>
        <span class="cv-card__ext" aria-hidden="true">阅读 →</span>
      </p>
    </div>
  </a>
</template>
