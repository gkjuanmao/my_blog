<script setup lang="ts">
import type { Article, Category, PaginatedResponse } from '~/types/api'

definePageMeta({ layout: 'admin' })

const keyword = ref('')
const categorySlug = ref('')
const status = ref('') // '' | 'true' | 'false'
const sortOrder = ref<'asc' | 'desc'>('desc')

const categories = ref<Category[]>([])
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
    const params: Record<string, unknown> = {
      page: page.value,
      page_size: pageSize.value,
      ordering: sortOrder.value === 'asc' ? 'publish_time' : '-publish_time',
    }
    if (keyword.value.trim()) params.keyword = keyword.value.trim()
    if (categorySlug.value) params.category_slug = categorySlug.value
    if (status.value) params.is_published = status.value
    const { data } = await useApi().get<PaginatedResponse<Article>>('/admin/articles/', params)
    articles.value = data.items
    total.value = data.total
  } catch (e: any) {
    errorMsg.value = e?.data?.message ?? '加载失败'
  } finally {
    loading.value = false
  }
}

async function fetchCategories() {
  try {
    const { data } = await useApi().get<Category[]>('/categories/')
    categories.value = data
  } catch {
    categories.value = []
  }
}

/** 筛选/排序变化：回到第 1 页（已在第 1 页时直接刷新，避免 watch 不触发） */
function applyFilters() {
  if (page.value === 1) fetchArticles()
  else page.value = 1
}

function doSearch() {
  applyFilters()
}

function resetFilters() {
  keyword.value = ''
  categorySlug.value = ''
  status.value = ''
  sortOrder.value = 'desc'
  applyFilters()
}

/** el-table 自定义排序 → 服务端排序（仅发布时间列可排） */
function handleSortChange({ prop, order }: { prop: string | null; order: string | null }) {
  if (prop !== 'publish_time') return
  sortOrder.value = order === 'ascending' ? 'asc' : 'desc'
  applyFilters()
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
onMounted(() => {
  fetchCategories()
  fetchArticles()
})
</script>

<template>
  <div>
    <h1 class="text-xl font-semibold">文章管理</h1>
    <div class="space-y-4">
      <div class="flex flex-col gap-3">
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <el-input v-model="keyword" placeholder="按标题搜索…" clearable @keyup.enter="doSearch" />
          <el-select
            v-model="categorySlug"
            class="w-full"
            placeholder="按分类搜索"
            clearable
            @change="applyFilters"
          >
            <el-option v-for="c in categories" :key="c.id" :label="c.name" :value="c.slug" />
          </el-select>
          <el-select
            v-model="status"
            class="w-full"
            placeholder="按状态搜索"
            clearable
            @change="applyFilters"
          >
            <el-option label="已发布" value="true" />
            <el-option label="草稿" value="false" />
          </el-select>
          <!-- 移动端无表头，排序在此控制；桌面端用「发布时间」列表头排序 -->
          <el-select v-model="sortOrder" class="w-full md:hidden" @change="applyFilters">
            <el-option label="发布时间：最新在前" value="desc" />
            <el-option label="发布时间：最早在前" value="asc" />
          </el-select>
        </div>
        <div class="flex flex-wrap gap-3">
          <el-button type="warning" @click="doSearch">搜索</el-button>
          <el-button @click="resetFilters">重置</el-button>
          <el-button type="primary" class="ml-auto" @click="goCreate">新建文章</el-button>
        </div>
      </div>

      <div v-if="errorMsg" class="py-8 text-center text-sm text-red-500">{{ errorMsg }}</div>
      <template v-else>
        <div v-loading="loading" class="hidden overflow-x-auto md:block">
          <el-table
            :data="articles"
            border
            stripe
            :default-sort="{ prop: 'publish_time', order: 'descending' }"
            @sort-change="handleSortChange"
          >
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
            <el-table-column prop="publish_time" label="发布时间" width="180" sortable="custom">
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
