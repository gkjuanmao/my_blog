<script setup lang="ts">
/**
 * 后台页面抬头：eyebrow（中文 + 英文小字）→ 书法体标题 → 等宽 meta → 1px 线 + 48px 金段。
 * 四页与编辑页共用，保证「一页一个抬头」的节奏一致。
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
  <header class="ad-masthead">
    <p class="ad-eyebrow">
      {{ eyebrow }}
      <span v-if="eyebrowEn" class="ad-eyebrow__en">{{ eyebrowEn }}</span>
    </p>
    <div class="ad-masthead__row">
      <h1>{{ title }}</h1>
      <div v-if="$slots.actions" class="ad-masthead__actions">
        <slot name="actions" />
      </div>
    </div>
    <p v-if="meta || $slots.meta" class="ad-masthead__meta">
      <slot name="meta">{{ meta }}</slot>
    </p>
    <div class="ad-rule" aria-hidden="true"><i /></div>
  </header>
</template>
