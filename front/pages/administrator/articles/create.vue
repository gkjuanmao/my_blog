<script setup lang="ts">
import type { Category, Tag } from '~/types/api'

definePageMeta({ layout: 'admin' })

const categories = ref<Category[]>([])
const tags = ref<Tag[]>([])
const submitting = ref(false)

onMounted(async () => {
  const [catRes, tagRes] = await Promise.all([
    useApi().get<Category[]>('/categories/'),
    useApi().get<Tag[]>('/tags/'),
  ])
  categories.value = catRes.data
  tags.value = tagRes.data
})

async function handleSubmit(fd: FormData) {
  submitting.value = true
  try {
    await useApi().post('/admin/articles/', fd)
    ElMessage.success('创建成功')
    navigateTo('/administrator/articles')
  } catch (e: any) {
    ElMessage.error(e?.data?.message ?? '创建失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div>
    <h1 class="text-xl font-semibold">新建文章</h1>
    <ArticleForm submit-label="创建" :categories="categories" :tags="tags" :loading="submitting" @submit="handleSubmit" />
  </div>
</template>
