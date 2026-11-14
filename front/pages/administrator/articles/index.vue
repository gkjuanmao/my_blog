<script setup lang="ts">
// 文章管理：列表 + 筛选/排序 + 选择导出 + 批量删除 + 归档导入
//
// 本文件只保留「页面级」状态与调度：筛选条件、勾选集合、增删改导航、列表加载。
// 视图与归档流程在 components/admin/ 下的组件里（桌面台账表 / 移动卡片 / 筛选 / 导出 / 导入）。
import type {
  Article,
  BulkDeleteResult,
  Category,
  PaginatedResponse,
} from '~/types/api'
import { useArticleList } from '~/composables/useArticleList'

definePageMeta({ layout: 'admin' })

const route = useRoute()
const keyword = ref('')
const categorySlug = ref(typeof route.query.category === 'string' ? route.query.category : '')
const status = ref('') // '' | 'true' | 'false'
const sortOrder = ref<'asc' | 'desc'>('desc')
const categories = ref<Category[]>([])

const { page, pageSize, articles, total, loading, errorMsg, load } = useArticleList()

// 导入改成异步任务后，本页拿不到「导入完成」事件（弹窗提交完就关了）。
// 任务终态时单例把 finishedTick +1，这里据此刷新列表——只在本页可见时才刷。
const { finishedTick } = useImportTasks()
watch(finishedTick, () => {
  if (import.meta.client && document.hidden) return
  void fetchArticles()
})

/** 当前勾选的文章 id（切换分页时清空） */
const selectedIds = ref<number[]>([])
const importVisible = ref(false)
const bulkDeleting = ref(false)
/** 转移归属：超管专属（后端 /admin/articles/bulk-author/ 同样是超级管理员鉴权） */
const transferVisible = ref(false)
const { isSuperuser, ensureMe } = useMe()

/** 抬头里的筛选说明：只说当前生效的条件 */
const filterSummary = computed(() => {
  const parts: string[] = [`共 ${total.value} 篇`]
  if (keyword.value.trim()) parts.push(`关键词「${keyword.value.trim()}」`)
  if (categorySlug.value) {
    const name = categories.value.find(c => c.slug === categorySlug.value)?.name
    if (name) parts.push(`栏目「${name}」`)
  }
  if (status.value === 'true') parts.push('只看已发布')
  if (status.value === 'false') parts.push('只看草稿')
  parts.push(`按发布时间${sortOrder.value === 'desc' ? '新 → 旧' : '旧 → 新'}`)
  return parts.join(' · ')
})

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

function resetFilters() {
  keyword.value = ''
  categorySlug.value = ''
  status.value = ''
  sortOrder.value = 'desc'
  applyFilters()
}

/** 表头「发布时间」点击 → 服务端排序（direction 用 el-table 的语义，兼容原回调） */
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
    await ElMessageBox.confirm(`确定删除文章「${row.title}」吗？封面与附件会一并清理。`, '删除文章', {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
    })
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
    ? selectedIds.value.filter(value => value !== id)
    : [...selectedIds.value, id]
}

const allSelectedOnPage = computed(
  () => articles.value.length > 0 && selectedIds.value.length === articles.value.length,
)

/** 全选/取消全选当前页（勾选集合是唯一数据源，表格与卡片都受控） */
function toggleSelectAllOnPage() {
  selectedIds.value = allSelectedOnPage.value ? [] : articles.value.map(row => row.id)
}

/* ------------------------------------------------------------------ 批量删除 */

async function doBulkDelete() {
  const count = selectedIds.value.length
  if (!count) return
  try {
    await ElMessageBox.confirm(
      `确定删除选中的 ${count} 篇文章吗？其封面与附件文件会一并清除，且不可恢复。`,
      '批量删除',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
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
  void ensureMe()
})
</script>

<template>
  <div>
    <AdminMasthead eyebrow="稿件" eyebrow-en="Manuscripts" title="文章管理" :meta="filterSummary">
      <template #actions>
        <button class="ad-btn ad-btn--ghost" type="button" @click="importVisible = true">
          导入归档
        </button>
        <button class="ad-btn ad-btn--primary" type="button" @click="goCreate">新建文章</button>
      </template>
    </AdminMasthead>

    <ArticleAdminFilters
      v-model:keyword="keyword"
      v-model:category-slug="categorySlug"
      v-model:status="status"
      v-model:sort-order="sortOrder"
      :categories="categories"
      @change="applyFilters"
      @search="applyFilters"
    />

    <div class="ad-toolbar">
      <ArticleExportBar
        :keyword="keyword"
        :category-slug="categorySlug"
        :status="status"
        :selected-ids="selectedIds"
      />
      <button class="ad-btn ad-btn--text ad-btn--sm" type="button" @click="resetFilters">
        重置筛选
      </button>
      <span class="ad-toolbar__spacer" />
      <button
        v-if="articles.length"
        class="ad-btn ad-btn--text ad-btn--sm"
        type="button"
        @click="toggleSelectAllOnPage"
      >
        {{ allSelectedOnPage ? '取消全选本页' : '全选本页' }}
      </button>
    </div>

    <div v-if="selectedIds.length" class="ad-selbar">
      <p>已选 <b>{{ selectedIds.length }}</b> 篇</p>
      <button
        v-if="isSuperuser"
        class="ad-link"
        type="button"
        @click="transferVisible = true"
      >
        转移归属
      </button>
      <button
        class="ad-link ad-link--danger"
        type="button"
        :disabled="bulkDeleting"
        @click="doBulkDelete"
      >
        {{ bulkDeleting ? '正在删除…' : '批量删除' }}
      </button>
      <button class="ad-link ad-selbar__clear" type="button" @click="clearSelection">
        清空选择
      </button>
    </div>

    <div v-if="errorMsg" role="alert" style="padding: 40px 0">
      <p class="ad-error">{{ errorMsg }}</p>
      <button class="ad-btn ad-btn--ghost ad-btn--sm" type="button" style="margin-top: 14px" @click="fetchArticles">
        重试
      </button>
    </div>
    <template v-else>
      <ArticleListTable
        :articles="articles"
        :loading="loading"
        :selected-ids="selectedIds"
        :order="sortOrder"
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

    <AdminPager
      v-if="total > 0"
      v-model:page="page"
      v-model:page-size="pageSize"
      :total="total"
      :page-sizes="[10, 20, 50]"
    />

    <ArticleImportDialog v-model="importVisible" />
    <AuthorTransferDialog
      v-if="isSuperuser"
      v-model="transferVisible"
      :ids="selectedIds"
      @done="clearSelection(); fetchArticles()"
    />
  </div>
</template>
