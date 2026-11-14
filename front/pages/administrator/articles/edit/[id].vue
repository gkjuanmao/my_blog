<script setup lang="ts">
import type { AdminArticleDetail, AdminUser, Category, Tag } from '~/types/api'

definePageMeta({ layout: 'admin' })

const route = useRoute()
// 必须是 computed：同路由仅 :id 变化时组件实例复用、setup 不会重跑，
// 写成常量会让后续切换编辑对象仍请求旧 id。
const id = computed(() => Number(route.params.id))

const article = ref<AdminArticleDetail | null>(null)
const categories = ref<Category[]>([])
/** 作者候选：只给超管拉（转移归属是超管专属操作，后端同样校验） */
const authorOptions = ref<Array<{ id: number; username: string }>>([])
const { isSuperuser, ensureMe } = useMe()
const tags = ref<Tag[]>([])
const loading = ref(true)
const submitting = ref(false)
const errorMsg = ref('')
const guard = useRequestGuard()

async function loadData() {
  const seq = guard.begin()
  loading.value = true
  errorMsg.value = ''
  try {
    const [artRes, catRes, tagRes] = await Promise.all([
      useApi().get<AdminArticleDetail>(`/admin/articles/${id.value}/`),
      useApi().get<Category[]>('/categories/'),
      useApi().get<Tag[]>('/tags/'),
    ])
    if (!guard.isLatest(seq)) return
    article.value = artRes.data
    categories.value = catRes.data
    tags.value = tagRes.data

    await ensureMe()
    if (isSuperuser.value) {
      // 只在超管下多取一次用户列表；失败不影响编辑（顶多不显示作者下拉）
      try {
        const usersRes = await useApi().get<{ items: AdminUser[] }>('/admin/users/', {
          page_size: 100,
          ordering: 'username',
        })
        authorOptions.value = usersRes.data.items
          .filter(u => u.is_active)
          .map(u => ({ id: u.id, username: u.username }))
      } catch {
        authorOptions.value = []
      }
    }
  } catch (e) {
    if (!guard.isLatest(seq)) return
    errorMsg.value = errorMessage(e, '文章不存在')
  } finally {
    if (guard.isLatest(seq)) loading.value = false
  }
}

onMounted(loadData)
watch(id, loadData)

async function handleSubmit(fd: FormData) {
  submitting.value = true
  try {
    await useApi().put(`/admin/articles/${id.value}/`, fd)
    ElMessage.success('保存成功')
    navigateTo('/administrator/articles')
  } catch (e) {
    ElMessage.error(errorMessage(e, '保存失败'))
  } finally {
    submitting.value = false
  }
}

const meta = computed(() => {
  if (!article.value) return ''
  return `${article.value.slug} · 更新于 ${formatDateTime(article.value.updated_at)}`
})
</script>

<template>
  <div>
    <AdminMasthead eyebrow="稿件" eyebrow-en="Manuscript" title="编辑文章" :meta="meta">
      <template #actions>
        <NuxtLink class="ad-btn ad-btn--ghost" to="/administrator/articles">返回列表</NuxtLink>
      </template>
    </AdminMasthead>

    <div v-if="loading" class="ad-loading" style="padding: 60px 0; color: var(--hp-ink-3)">
      正在取稿…
    </div>
    <div v-else-if="errorMsg" role="alert" style="padding: 40px 0">
      <p class="ad-error">{{ errorMsg }}</p>
      <NuxtLink class="ad-btn ad-btn--ghost ad-btn--sm" to="/administrator/articles" style="margin-top: 14px">
        返回列表
      </NuxtLink>
    </div>
    <ArticleForm
      v-else
      :initial="article"
      submit-label="保存修改"
      :categories="categories"
      :tags="tags"
      :author-options="authorOptions"
      :loading="submitting"
      @submit="handleSubmit"
    />
  </div>
</template>
