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
  } catch (e) {
    ElMessage.error(errorMessage(e, '创建失败'))
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div>
    <AdminMasthead
      eyebrow="稿件"
      eyebrow-en="New entry"
      title="新建文章"
      meta="写完可先存为草稿，满意了再把状态切到「已发布」。"
    >
      <template #actions>
        <NuxtLink class="ad-btn ad-btn--ghost" to="/administrator/articles">返回列表</NuxtLink>
      </template>
    </AdminMasthead>

    <ArticleForm
      submit-label="创建文章"
      :categories="categories"
      :tags="tags"
      :loading="submitting"
      @submit="handleSubmit"
    />
  </div>
</template>
