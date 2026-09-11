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
  navigateTo('/administrator/articles/create')
}
function goEdit(id: number) {
  navigateTo(`/administrator/articles/edit/${id}`)
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
      <div class="flex flex-col gap-3 sm:flex-row sm:items-center">
        <el-input v-model="keyword" placeholder="按标题搜索…" clearable @keyup.enter="doSearch" />
        <div class="flex gap-3">
          <el-button type="warning" @click="doSearch">搜索</el-button>
          <el-button type="primary" @click="goCreate">新建文章</el-button>
        </div>
      </div>

      <div v-if="errorMsg" class="py-8 text-center text-sm text-red-500">{{ errorMsg }}</div>
      <template v-else>
        <div v-loading="loading" class="hidden overflow-x-auto md:block">
          <el-table :data="articles" border stripe>
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
        </div>

        <div v-loading="loading" class="space-y-3 md:hidden">
          <div
            v-for="row in articles"
            :key="row.id"
            class="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-700 dark:bg-stone-900"
          >
            <div class="flex items-start justify-between gap-3">
              <h3 class="font-medium text-stone-900 dark:text-stone-100">{{ row.title }}</h3>
              <el-tag :type="row.is_published ? 'success' : 'info'" size="small">
                {{ row.is_published ? '已发布' : '草稿' }}
              </el-tag>
            </div>
            <div class="mt-2 space-y-1 text-xs text-stone-500 dark:text-stone-400">
              <div>分类：{{ row.category?.name ?? '—' }}</div>
              <div>发布时间：{{ new Date(row.publish_time).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) }}</div>
            </div>
            <div class="mt-3 flex justify-end gap-2">
              <el-button link type="primary" @click="goEdit(row.id)">编辑</el-button>
              <el-button link type="danger" @click="handleDelete(row)">删除</el-button>
            </div>
          </div>
          <div v-if="!loading && articles.length === 0" class="py-8 text-center text-sm text-stone-400">暂无文章</div>
        </div>
      </template>

      <div v-if="total > 0" class="flex justify-center">
        <AppPagination v-model:page="page" v-model:page-size="pageSize" :total="total" />
      </div>
    </div>
  </div>
</template>
