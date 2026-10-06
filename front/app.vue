<script setup lang="ts">
const { site } = useAppConfig()

// 标题模板：页面标题 === 站点名（首页）时不重复拼接
useHead({
  titleTemplate: (title?: string) =>
    !title || title === site.name ? site.name : `${title} · ${site.name}`,
})
</script>

<template>
  <NuxtLayout>
    <NuxtPage />
  </NuxtLayout>
</template>