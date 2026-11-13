<script setup lang="ts">
/**
 * 详情页纸纹切换器（底部浮条）
 *
 * 只做三件事：把选择写到 <html data-tex>、存 localStorage、给出可访问的按钮组。
 * 颜色与铺法全部在 assets/css/home-cover.css §19.1，这里不持有任何视觉数值。
 *
 * ⚠️ 纹理层依赖 `html.art-page` + `.public-shell { isolation: isolate }`，
 *    两处都在 CSS 里；这个组件只负责切 data-tex。
 */
type TexKey =
  | 'paper-fiber'
  | 'xuan-paper'
  | 'quartz-sand'
  | 'lime-plaster'
  | 'linen-weave'
  | 'cloud-stone'
  | 'none'

interface TexOption {
  key: TexKey
  label: string
  hint: string
  file?: string
}

const OPTIONS: TexOption[] = [
  { key: 'paper-fiber', label: '棉纸', hint: '手工棉纸纤维 · 最接近旅行手记', file: 'swatch-paper-fiber.webp' },
  { key: 'xuan-paper', label: '宣纸', hint: '宣纸帘纹 · 横向细纹', file: 'swatch-xuan-paper.webp' },
  { key: 'quartz-sand', label: '石英砂', hint: '细石英砂 · 最克制的底噪', file: 'swatch-quartz-sand.webp' },
  { key: 'lime-plaster', label: '石灰膏', hint: '石灰膏墙 · 大云斑、空间感最强', file: 'swatch-lime-plaster.webp' },
  { key: 'linen-weave', label: '亚麻', hint: '亚麻织物 · 布面手账感', file: 'swatch-linen-weave.webp' },
  { key: 'cloud-stone', label: '云雾石', hint: '云雾石 · 矿物云斑', file: 'swatch-cloud-stone.webp' },
  { key: 'none', label: '无', hint: '关掉纸纹，回到纯色底' },
]

const STORE_KEY = 'blog-article-texture'
const DEFAULT_TEX: TexKey = 'cloud-stone'

const current = ref<TexKey>(DEFAULT_TEX)
const currentLabel = computed(() => OPTIONS.find((o) => o.key === current.value)?.label ?? '')
/** 窄屏默认收起成一个按钮，点开才铺色块（否则会挡住正文） */
const expanded = ref(false)
const currentSwatch = computed(() => OPTIONS.find((o) => o.key === current.value)?.file)

function apply(key: TexKey) {
  document.documentElement.dataset.tex = key
}

function remember(key: TexKey) {
  try {
    localStorage.setItem(STORE_KEY, key)
  } catch {
    // 隐私模式下 localStorage 可能抛错：切换仍然生效，只是不记忆
  }
}

function select(key: TexKey) {
  if (current.value !== key) {
    current.value = key
    apply(key)
    remember(key)
  }
  expanded.value = false
}

onMounted(() => {
  let saved: string | null = null
  try {
    saved = localStorage.getItem(STORE_KEY)
  } catch {
    saved = null
  }
  const hit = OPTIONS.find((o) => o.key === saved)
  if (hit) current.value = hit.key
  apply(current.value)
})

// 离开详情页时摘掉 data-tex，避免它在别的页面残留（CSS 本就以 html.art-page 限定）
onBeforeUnmount(() => {
  delete document.documentElement.dataset.tex
})

const thumbVar = (file?: string) => (file ? { '--sw-thumb': `url('/texture/${file}')` } : undefined)
</script>

<template>
  <div class="cv-texpick" :class="{ 'is-open': expanded }" role="group" aria-label="背景纸纹">
    <button
      type="button"
      class="cv-texpick__toggle"
      :aria-expanded="expanded"
      aria-label="切换背景纸纹"
      @click="expanded = !expanded"
    >
      <span
        class="cv-texpick__toggle-face"
        :style="currentSwatch ? { '--sw-thumb': `url('/texture/${currentSwatch}')` } : undefined"
      />
    </button>
    <span class="cv-texpick__label" aria-hidden="true">
      纸纹<span class="cv-texpick__now">{{ currentLabel }}</span>
    </span>
    <button
      v-for="option in OPTIONS"
      :key="option.key"
      type="button"
      class="cv-texpick__sw"
      :class="{ 'cv-texpick__sw--none': !option.file }"
      :style="thumbVar(option.file)"
      :aria-pressed="current === option.key"
      :aria-label="`纸纹：${option.label}（${option.hint}）`"
      :title="option.hint"
      @click="select(option.key)"
    >
      <template v-if="!option.file">无</template>
    </button>
  </div>
</template>
