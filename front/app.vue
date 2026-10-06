<script setup lang="ts">
const SITE_NAME = '旅行游记'

// 标题模板：页面标题 === 站点名（首页）时不重复拼接
useHead({
  titleTemplate: (title?: string) =>
    !title || title === SITE_NAME ? SITE_NAME : `${title} · ${SITE_NAME}`,
})
</script>

<template>
  <NuxtLayout>
    <NuxtPage />
  </NuxtLayout>
</template>