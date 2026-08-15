<script setup lang="ts">
import type { Article, PaginatedResponse } from '~/types/api'

definePageMeta({ layout: 'admin' })

const keyword = ref('')
const page = ref(1)
const pageSize = ref(10)
const articles = ref<Article[]>([])
const total = ref(0)
const loading = ref(false)
const errorMsg = ref('')

async function fetchArticles() {
  loading.value = true
  errorMsg.value = ''
  try {
    const params: Record<string, unknown> = { page: page.value, page_size: pageSize.value }
    if (keyword.value.trim()) params.keyword = keyword.value.trim()
    const { data } = await useApi().get<PaginatedResponse<Article>>('/admin/articles/', params)
    articles.value = data.items
    total.value = data.total
  } catch (e: any) {
    errorMsg.value = e?.data?.message ?? '加载失败'
  } finally {
    loading.value = false
  }
}

function doSearch() {
  page.value = 1
  fetchArticles()
}

function goCreate() {
  navigateTo('/admin/articles/create')
}
function goEdit(id: number) {
  navigateTo(`/admin/articles/edit/${id}`)
}
async function handleDelete(row: Article) {
  try {
    await ElMessageBox.confirm(`确定删除文章「${row.title}」吗？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await useApi().del(`/admin/articles/${row.id}/`)
    ElMessage.success('删除成功')
    fetchArticles()
  } catch (e: any) {
    ElMessage.error(e?.data?.message ?? '删除失败')
  }
}

watch([page, pageSize], fetchArticles)
onMounted(fetchArticles)
</script>

<template>
  <div>
    <h1 class="text-xl font-semibold">文章管理</h1>
    <div class="space-y-4">
      <div class="flex items-center gap-3">
        <el-input v-model="keyword" placeholder="按标题搜索…" clearable @keyup.enter="doSearch" />
        <el-button type="warning" @click="doSearch">搜索</el-button>
        <el-button type="primary" @click="goCreate">新建文章</el-button>
      </div>

      <div v-if="errorMsg" class="py-8 text-center text-sm text-red-500">{{ errorMsg }}</div>
      <el-table v-else :data="articles" v-loading="loading" border stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="title" label="标题" min-width="180" />
        <el-table-column label="分类" width="120">
          <template #default="{ row }: { row: any }">
            {{ row.category?.name ?? '—' }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }: { row: any }">
            <el-tag :type="row.is_published ? 'success' : 'info'" size="small">
              {{ row.is_published ? '已发布' : '草稿' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="发布时间" width="170">
          <template #default="{ row }: { row: any }">
            {{ new Date(row.publish_time).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140">
          <template #default="{ row }: { row: any }">
            <el-button link type="primary" @click="goEdit(row.id)">编辑</el-button>
            <el-button link type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div v-if="total > 0" class="flex justify-center">
        <AppPagination v-model:page="page" v-model:page-size="pageSize" :total="total" />
      </div>
    </div>
  </div>
</template>
