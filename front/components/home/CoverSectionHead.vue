<script setup lang="ts">
/**
 * 区块标题条（`#journal` 的标题）。
 * eyebrow 是标签不是标题（用 <p>，不进 outline），`共 N 篇` 是内容不是装饰（保留语义）。
 */
defineProps<{ total: number }>()
</script>

<template>
  <div class="cv-section-head">
    <div class="cv-section-head__top">
      <div>
        <p class="cv-section-head__eyebrow">
          文章 / <span lang="en">JOURNAL</span>
        </p>
        <h2 id="journal-heading" class="cv-section-head__title">最新文章</h2>
      </div>
      <p class="cv-section-head__count">共 {{ total }} 篇</p>
    </div>
    <div class="cv-section-head__line" aria-hidden="true"/>
  </div>
</template>
