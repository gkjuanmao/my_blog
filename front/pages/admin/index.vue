<script setup lang="ts">
definePageMeta({ layout: 'admin' })

onMounted(() => {
  navigateTo('/admin/dashboard', { redirectCode: 301 })
})
</script>

<template>
  <div />
</template>
