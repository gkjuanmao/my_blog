<script setup lang="ts">
import type { AdminArticleDetail, Category, Tag } from '~/types/api'

definePageMeta({ layout: 'admin' })

const route = useRoute()
const id = Number(route.params.id)

const article = ref<AdminArticleDetail | null>(null)
const categories = ref<Category[]>([])
const tags = ref<Tag[]>([])
const loading = ref(true)
const submitting = ref(false)
const errorMsg = ref('')

onMounted(async () => {
  try {
    const [artRes, catRes, tagRes] = await Promise.all([
      useApi().get<AdminArticleDetail>(`/admin/articles/${id}/`),
      useApi().get<Category[]>('/categories/'),
      useApi().get<Tag[]>('/tags/'),
    ])
    article.value = artRes.data
    categories.value = catRes.data
    tags.value = tagRes.data
  } catch (e: any) {
    errorMsg.value = e?.data?.message ?? '文章不存在'
  } finally {
    loading.value = false
  }
})

async function handleSubmit(fd: FormData) {
  submitting.value = true
  try {
    await useApi().put(`/admin/articles/${id}/`, fd)
    ElMessage.success('保存成功')
    navigateTo('/administrator/articles')
  } catch (e: any) {
    ElMessage.error(e?.data?.message ?? '保存失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div>
    <h1 class="text-xl font-semibold">编辑文章</h1>
    <div v-if="loading" class="py-12 text-center text-sm text-stone-400">加载中…</div>
    <div v-else-if="errorMsg" class="py-12 text-center">
      <p class="mb-4 text-sm text-red-500">{{ errorMsg }}</p>
      <NuxtLink to="/administrator/articles" class="text-sm text-brand-600 hover:underline">返回列表</NuxtLink>
    </div>
    <ArticleForm v-else :initial="article" submit-label="保存" :categories="categories" :tags="tags" :loading="submitting" @submit="handleSubmit" />
  </div>
</template>
