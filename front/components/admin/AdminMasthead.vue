<script setup lang="ts">
/**
 * 后台页面抬头：eyebrow（中文 + 英文小字）→ 宋体标题 → 等宽 meta → 1px 线 + 62px 金段。
 * 六个页面与编辑页共用，保证「一页一个抬头」的节奏一致。
 */
withDefaults(
  defineProps<{
    /** 中文 eyebrow，如「稿件」 */
    eyebrow: string
    /** 英文小字，如「Manuscripts」 */
    eyebrowEn?: string
    title: string
    /** 等宽 meta 行；需要富文本时用 #meta 插槽 */
    meta?: string
  }>(),
  { eyebrowEn: '', meta: '' },
)
</script>

<template>
  <header class="ad-mast">
    <p class="ad-eyebrow">
      {{ eyebrow }}
      <em v-if="eyebrowEn" class="ad-eyebrow__en">{{ eyebrowEn }}</em>
    </p>
    <div class="ad-mast__row">
      <div>
        <h1>{{ title }}</h1>
        <p v-if="meta || $slots.meta" class="ad-mast__meta">
          <slot name="meta">{{ meta }}</slot>
        </p>
      </div>
      <div v-if="$slots.actions" class="ad-mast__acts">
        <slot name="actions" />
      </div>
    </div>
    <div class="ad-rule" aria-hidden="true" />
  </header>
</template>
