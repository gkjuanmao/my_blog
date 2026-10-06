<script setup lang="ts">
// 文章管理：列表 + 筛选/排序 + 选择导出 + 批量删除 + 归档导入
//
// FE-09 拆分后本文件只保留「页面级」状态与调度：筛选条件、勾选集合、增删改导航、
// 以及列表加载。视图与归档流程分别在 components/admin/ 下的四个组件里。
import type {
  Article,
  BulkDeleteResult,
  Category,
  PaginatedResponse,
} from '~/types/api'
import { useArticleList } from '~/composables/useArticleList'

definePageMeta({ layout: 'admin' })

const keyword = ref('')
const categorySlug = ref('')
const status = ref('') // '' | 'true' | 'false'
const sortOrder = ref<'asc' | 'desc'>('desc')
const categories = ref<Category[]>([])

const { page, pageSize, articles, total, loading, errorMsg, load } = useArticleList()

/** 当前勾选的文章 id（切换分页时清空） */
const selectedIds = ref<number[]>([])
const importVisible = ref(false)
const bulkDeleting = ref(false)

function fetchArticles() {
  // onLoaded：仅在响应仍是最新时清空勾选（避免乱序响应把新页的勾选清掉）
  return load(async (pageNum, size) => {
    const params: Record<string, unknown> = {
      page: pageNum,
      page_size: size,
      ordering: sortOrder.value === 'asc' ? 'publish_time' : '-publish_time',
    }
    if (keyword.value.trim()) params.keyword = keyword.value.trim()
    if (categorySlug.value) params.category_slug = categorySlug.value
    if (status.value) params.is_published = status.value
    const { data } = await useApi().get<PaginatedResponse<Article>>('/admin/articles/', params)
    return data
  }, clearSelection)
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
  } catch (e) {
    ElMessage.error(errorMessage(e, '删除失败'))
  }
}

/* ------------------------------------------------------------------ 勾选 */

function clearSelection() {
  selectedIds.value = []
}
function toggleSelect(id: number) {
  selectedIds.value = selectedIds.value.includes(id)
    ? selectedIds.value.filter((value) => value !== id)
    : [...selectedIds.value, id]
}

const allSelectedOnPage = computed(
  () => articles.value.length > 0 && selectedIds.value.length === articles.value.length,
)

/** 全选/取消全选当前页（勾选集合是唯一数据源，表格与卡片都受控） */
function toggleSelectAllOnPage() {
  selectedIds.value = allSelectedOnPage.value
    ? []
    : articles.value.map((row) => row.id)
}

/* ------------------------------------------------------------------ 批量删除 */

async function doBulkDelete() {
  const count = selectedIds.value.length
  if (!count) {
    ElMessage.warning('请先勾选要删除的文章')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确定删除选中的 ${count} 篇文章吗？其封面与附件文件会一并清除，且不可恢复。`,
      '批量删除确认',
      { type: 'warning', confirmButtonText: '确认删除' },
    )
  } catch {
    return
  }

  bulkDeleting.value = true
  try {
    const { data } = await useApi().post<BulkDeleteResult>('/admin/articles/bulk-delete/', {
      ids: selectedIds.value,
    })
    if (data.not_found.length) {
      ElMessage.warning(
        `已删除 ${data.deleted} 篇；${data.not_found.length} 篇已不存在（可能已被删除）`,
      )
    } else {
      ElMessage.success(`已删除 ${data.deleted} 篇文章`)
    }
    // 当前页被删空且不在第 1 页 → 退一页（watch 会触发刷新）
    if (articles.value.length - data.deleted <= 0 && page.value > 1) page.value -= 1
    else fetchArticles()
  } catch (e) {
    ElMessage.error(errorMessage(e, '批量删除失败'))
  } finally {
    bulkDeleting.value = false
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
        <ArticleAdminFilters
          v-model:keyword="keyword"
          v-model:category-slug="categorySlug"
          v-model:status="status"
          v-model:sort-order="sortOrder"
          :categories="categories"
          @change="applyFilters"
          @search="doSearch"
        />
        <!--
          工具栏配色约定（与「分类管理 / 标签管理」对齐）：
          - warning（品牌琥珀色）= 页面主操作：搜索、新建文章
          - default              = 中性/次要操作：重置、导出、导入
          - danger plain         = 破坏性操作：批量删除
          - link primary         = 辅助链接：全选本页
          分组用竖线分隔：筛选 │ 归档 │ 删除 ……… 全选 / 新建
        -->
        <div class="flex flex-wrap items-center gap-2">
          <el-button type="warning" @click="doSearch">搜索</el-button>
          <el-button @click="resetFilters">重置</el-button>

          <span class="mx-1 h-6 w-px bg-stone-300 dark:bg-stone-700" />

          <ArticleExportBar
            :keyword="keyword"
            :category-slug="categorySlug"
            :status="status"
            :selected-ids="selectedIds"
          />
          <el-button @click="importVisible = true">导入</el-button>

          <span class="mx-1 h-6 w-px bg-stone-300 dark:bg-stone-700" />

          <el-button
            type="danger"
            plain
            :disabled="!selectedIds.length || bulkDeleting"
            :loading="bulkDeleting"
            @click="doBulkDelete"
          >
            批量删除{{ selectedIds.length ? ` (${selectedIds.length})` : '' }}
          </el-button>

          <div class="ml-auto flex items-center gap-2">
            <el-button v-if="articles.length" link type="primary" @click="toggleSelectAllOnPage">
              {{ allSelectedOnPage ? '取消全选本页' : '全选本页' }}
            </el-button>
            <el-button type="warning" @click="goCreate">新建文章</el-button>
          </div>
        </div>
      </div>

      <div v-if="errorMsg" class="py-8 text-center text-sm text-red-500">{{ errorMsg }}</div>
      <template v-else>
        <ArticleListTable
          :articles="articles"
          :loading="loading"
          :selected-ids="selectedIds"
          @sort-change="handleSortChange"
          @toggle-select="toggleSelect"
          @toggle-select-all="toggleSelectAllOnPage"
          @edit="goEdit"
          @delete="handleDelete"
        />
        <ArticleMobileCards
          :articles="articles"
          :loading="loading"
          :selected-ids="selectedIds"
          @toggle-select="toggleSelect"
          @edit="goEdit"
          @delete="handleDelete"
        />
      </template>

      <div v-if="total > 0" class="flex justify-center">
        <AppPagination v-model:page="page" v-model:page-size="pageSize" :total="total" />
      </div>
    </div>

    <ArticleImportDialog v-model="importVisible" @imported="fetchArticles" />
  </div>
</template>