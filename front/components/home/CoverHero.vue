<script setup lang="ts">
/**
 * 首页 Hero（卷首）。
 *
 * 结构对应 01-visual-spec.md §6.2 的六层叠加：照片 → 调色片 → 侧/顶遮罩 → 极光 → 颗粒 → 等高线 → 底部渐隐 → 内容。
 * 装饰层（遮罩 / 极光 / 颗粒 / 等高线 / 竖排 / 滚动提示 / 印章）全部 `aria-hidden` + `pointer-events:none`，
 * 语义只由 h1 + meta + 两个 CTA 承担。
 */
import type { Article } from '~/types/api'

const props = defineProps<{
  /** 当页第一条（取自真实 API，可为空：渐变底 + 标语仍然成立） */
  article: Article | null
  total: number
  siteName: string
}>()

const emit = defineEmits<{ jump: [] }>()

/** 照片是否可用：无 URL / 加载失败 → 走无图降级（渐变底 + 颗粒 + 等高线，不是白块） */
const photoFailed = ref(false)
const coverUrl = computed(() => props.article?.cover_image_url ?? '')
const showPhoto = computed(() => Boolean(coverUrl.value) && !photoFailed.value)

// 换页后 hero 会换图，失败标记要一起重置，否则新图永远不被尝试
watch(coverUrl, () => {
  photoFailed.value = false
})

/** 印章 = 站点名首字（装饰，无信息量） */
const sealChar = computed(() => props.siteName.trim().charAt(0))

/** 等高线（4 条，viewBox 0 0 400 800，preserveAspectRatio=none） */
const contours = [
  'M-30 90 C 90 20, 250 190, 430 110',
  'M-30 250 C 110 180, 270 350, 430 270',
  'M-30 430 C 120 350, 260 540, 430 440',
  'M-30 620 C 100 540, 280 720, 430 630',
]

/** meta 行：规模感 + 更新年份；total 为 0 时整行不渲染 */
const metaText = computed(() => {
  if (props.total <= 0) return ''
  const iso = props.article?.publish_time
  const year = iso ? formatDateCompact(iso).slice(0, 4) : ''
  return year ? `共 ${props.total} 篇 · 更新至 ${year}` : `共 ${props.total} 篇`
})

/**
 * 「开始阅读 ↓」是页内锚点。目标 #journal 带 tabindex="-1"，
 * 否则按完 Tab 会弹回次 CTA，用户会以为没跳转。
 */
function onJump(event: MouseEvent) {
  const target = document.getElementById('journal')
  if (!target) return
  event.preventDefault()
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  target.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'start' })
  target.focus({ preventScroll: true })
  emit('jump')
}
</script>

<template>
  <section
    class="cv-hero"
    :class="{ 'cv-hero--nophoto': !showPhoto }"
    aria-labelledby="hero-title"
  >
    <img
      v-if="showPhoto"
      class="cv-hero__photo"
      :src="coverUrl"
      alt=""
      aria-hidden="true"
      width="1600"
      height="900"
      fetchpriority="high"
      loading="eager"
      decoding="async"
      @error="photoFailed = true"
    >
    <span class="cv-hero__tone" aria-hidden="true"/>
    <span class="cv-hero__shade" aria-hidden="true"/>
    <span class="cv-hero__aurora" aria-hidden="true"/>
    <span class="cv-hero__grain" aria-hidden="true"/>
    <svg
      class="cv-hero__contours"
      viewBox="0 0 400 800"
      preserveAspectRatio="none"
      aria-hidden="true"
      focusable="false"
    >
      <path v-for="d in contours" :key="d" :d="d" pathLength="100" />
    </svg>
    <span class="cv-hero__fade" aria-hidden="true"/>

    <div class="cv-hero__inner">
      <div class="cv-hero__copy">
        <span v-if="sealChar" class="cv-hero__seal" aria-hidden="true">{{ sealChar }}</span>

        <p class="cv-hero__eyebrow">
          {{ siteName }} · <span lang="en">TRAVEL JOURNAL</span>
        </p>

        <span class="cv-hero__rule" aria-hidden="true"/>

        <h1 id="hero-title" class="cv-hero__title">
          记录山川湖海，<br>
          也收藏「<span class="cv-hero__hl">人间烟火<span class="cv-hero__glow" aria-hidden="true"/></span>」。
        </h1>

        <p v-if="metaText" class="cv-hero__meta">{{ metaText }}</p>

        <a
          class="cv-btn cv-btn--primary cv-hero__cta--primary"
          href="#journal"
          @click="onJump"
        >
          开始阅读 <span aria-hidden="true">↓</span>
        </a>
        <NuxtLink class="cv-btn cv-btn--ghost cv-hero__cta--ghost" to="/timeline">
          按时间轴浏览
        </NuxtLink>
      </div>
    </div>

    <!-- 竖排装饰与滚动提示是 hero 的直接子元素：绝对定位相对 .cv-hero，
         放在 .cv-hero__inner 里会以「文案块」为参照，和 CTA 撞在一起 -->
    <div class="cv-hero__vertical" aria-hidden="true">
      <span class="cv-hero__vertical-text">山 川 湖 海</span>
      <span class="cv-hero__vertical-line"/>
    </div>

    <div class="cv-scroll-cue" aria-hidden="true">
      <span class="cv-scroll-cue__label">向下滚动</span>
      <span class="cv-scroll-cue__line"><span class="cv-scroll-cue__dot"/></span>
    </div>
  </section>
</template>
