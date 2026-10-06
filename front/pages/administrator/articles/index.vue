<script setup lang="ts">
// 文章管理：列表 + 筛选/排序 + 选择导出 + 批量删除 + 归档导入
import type {
  TableInstance,
  UploadFile,
  UploadInstance,
  UploadProgressEvent,
  UploadRawFile,
  UploadRequestOptions,
  UploadUserFile,
} from 'element-plus'

import type {
  ApiError,
  ArchiveEstimate,
  ArchiveExportTicket,
  ArchiveLimits,
  ArchiveReport,
  ArchiveStrategy,
  Article,
  BulkDeleteResult,
  Category,
  PaginatedResponse,
} from '~/types/api'

/** el-upload 的 onError 回调参数类型（element-plus 未从根导出该类型） */
type UploadErrorEvent = Parameters<NonNullable<UploadRequestOptions['onError']>>[0]

definePageMeta({ layout: 'admin' })

const STAGE_URL = '/admin/articles/import/stage/'
const PLAN_URL = '/admin/articles/import/plan/'
const COMMIT_URL = '/admin/articles/import/commit/'

const keyword = ref('')
const categorySlug = ref('')
const status = ref('') // '' | 'true' | 'false'
const sortOrder = ref<'asc' | 'desc'>('desc')

const categories = ref<Category[]>([])
// 分页写进 URL：刷新/后退可回到原页（与公开列表口径一致，FE-17）
const { page, pageSize, clampPage } = usePageQuery()
const articles = ref<Article[]>([])
const total = ref(0)
const loading = ref(false)
const errorMsg = ref('')

/** 当前勾选的文章 id（切换分页时清空） */
const selectedIds = ref<number[]>([])
const tableRef = ref<TableInstance | null>(null)
const guard = useRequestGuard()

async function fetchArticles() {
  const seq = guard.begin()
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
    if (!guard.isLatest(seq)) return
    articles.value = data.items
    total.value = data.total
    clampPage(data.total, pageSize.value)
    clearSelection()
  } catch (e) {
    if (!guard.isLatest(seq)) return
    errorMsg.value = errorMessage(e, '加载失败')
  } finally {
    if (guard.isLatest(seq)) loading.value = false
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
  } catch (e) {
    ElMessage.error(errorMessage(e, '删除失败'))
  }
}

/* ------------------------------------------------------------------ 勾选 */

function clearSelection() {
  selectedIds.value = []
  tableRef.value?.clearSelection?.()
}
function handleSelectionChange(rows: Article[]) {
  selectedIds.value = rows.map((row) => row.id)
}
function isSelected(id: number) {
  return selectedIds.value.includes(id)
}
function toggleSelect(id: number) {
  selectedIds.value = isSelected(id)
    ? selectedIds.value.filter((value) => value !== id)
    : [...selectedIds.value, id]
}

const allSelectedOnPage = computed(
  () => articles.value.length > 0 && selectedIds.value.length === articles.value.length,
)

/** 全选/取消全选当前页（桌面端同步表格勾选状态，移动端只维护 id 集合） */
function toggleSelectAllOnPage() {
  const table = tableRef.value
  if (allSelectedOnPage.value) {
    selectedIds.value = []
    table?.clearSelection?.()
    return
  }
  selectedIds.value = articles.value.map((row) => row.id)
  articles.value.forEach((row) => table?.toggleRowSelection?.(row, true))
}

/* ------------------------------------------------------------------ 批量删除 */

const bulkDeleting = ref(false)

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

/* ------------------------------------------------------------------ 导出 */

const exporting = ref(false)

function formatBytes(bytes: number): string {
  if (!bytes) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`
}

function filterParams(): Record<string, unknown> {
  const params: Record<string, unknown> = {}
  if (keyword.value.trim()) params.keyword = keyword.value.trim()
  if (categorySlug.value) params.category_slug = categorySlug.value
  if (status.value) params.is_published = status.value
  return params
}

async function doExport(scope: 'selected' | 'filtered') {
  if (scope === 'selected' && selectedIds.value.length === 0) {
    ElMessage.warning('请先勾选要导出的文章')
    return
  }
  const params =
    scope === 'selected' ? { ids: selectedIds.value.join(',') } : filterParams()

  exporting.value = true
  try {
    const { data: estimate } = await useApi().get<ArchiveEstimate>(
      '/admin/articles/export/estimate/',
      params,
    )
    if (!estimate.count) {
      ElMessage.warning('没有符合条件的文章')
      return
    }
    if (!estimate.importable) {
      await ElMessageBox.alert(
        `该范围超出导入上限，导出后无法回导，已阻止：${estimate.blocking_reasons.join('；')}`,
        '无法导出',
        { type: 'error' },
      )
      return
    }
    await ElMessageBox.confirm(
      `共 ${estimate.count} 篇，源文件约 ${formatBytes(estimate.source_bytes)}（${estimate.entries} 个条目）。` +
        '包内含封面与附件，可直接再次导入，也可手工修改后导入。',
      '导出确认',
      { type: 'info', confirmButtonText: '开始导出' },
    )
    const { data: ticket } = await useApi().get<ArchiveExportTicket>(
      '/admin/articles/export/',
      params,
    )
    // 票据是一次性下载链接，交给浏览器原生下载（不占前端内存）
    useApi().openUrl(ticket.download_url)
    ElMessage.success(`已开始下载 ${ticket.filename}（${formatBytes(ticket.bytes)}）`)
  } catch (e) {
    // ElMessageBox 取消时 reject 的是字符串 'cancel'/'close'
    if (typeof e === 'string' && (e === 'cancel' || e === 'close')) return
    ElMessage.error(errorMessage(e, '导出失败'))
  } finally {
    exporting.value = false
  }
}

/* ------------------------------------------------------------------ 导入 */

const importVisible = ref(false)
const uploadRef = ref<UploadInstance | null>(null)
const fileList = ref<UploadUserFile[]>([])
const limits = ref<ArchiveLimits | null>(null)
const strategy = ref<ArchiveStrategy>('skip')
const autoCreateTaxonomy = ref(true)
const asDraft = ref(false)
const uploadPercent = ref(0)
const staging = ref(false)
const replanning = ref(false)
const committing = ref(false)
const stagedId = ref('')
/** 已成功预检的那个文件的 uid，用于区分“状态变化”与“换了文件” */
const stagedFileUid = ref<number | null>(null)
const report = ref<ArchiveReport | null>(null)
const committed = ref(false)
const fileError = ref('')

async function openImport() {
  importVisible.value = true
  resetImport()
  if (!limits.value) {
    try {
      const { data } = await useApi().get<ArchiveLimits>('/admin/articles/import/limits/')
      limits.value = data
    } catch {
      limits.value = null
    }
  }
}

function resetImport() {
  fileList.value = []
  uploadRef.value?.clearFiles?.()
  invalidateStaged()
  fileError.value = ''
  uploadPercent.value = 0
  strategy.value = 'skip'
  autoCreateTaxonomy.value = true
  asDraft.value = false
}

/** 作废已暂存的结果（换文件 / 移除文件 / 关闭对话框时） */
function invalidateStaged() {
  stagedId.value = ''
  report.value = null
  committed.value = false
  stagedFileUid.value = null
}

/**
 * 选文件时的校验。
 *
 * ⚠️ el-upload 的 `on-change` 不只在“用户选择文件”时触发：
 * `use-handlers` 在 ready→uploading→success（以及 fail）每次状态变化后都会
 * `emitChange`（见 element-plus/es/components/upload/src/use-handlers.mjs
 * 的 handleSuccess/handleError）。所以这里**绝不能无条件重置**暂存状态，
 * 否则刚预检成功就会被自己清空（stagedId 为空 → “确认导入”按钮永远置灰）。
 */
function onFileChange(file: UploadFile) {
  fileError.value = ''
  const raw: File | undefined = file?.raw
  if (!raw) return
  // 只有“换了另一个文件”才作废已有的暂存结果
  if (stagedFileUid.value !== null && stagedFileUid.value !== file.uid) {
    invalidateStaged()
  }
  if (!raw.name.toLowerCase().endsWith('.zip')) {
    fileError.value = '只支持 .zip 压缩包'
    fileList.value = []
    return
  }
  const maxBytes = limits.value?.max_upload_bytes
  if (maxBytes && raw.size > maxBytes) {
    fileError.value = `压缩包 ${formatBytes(raw.size)} 超过上限 ${formatBytes(maxBytes)}`
    fileList.value = []
  }
}

function onFileRemove() {
  invalidateStaged()
}

function onExceed(files: File[]) {
  uploadRef.value?.clearFiles?.()
  const file = files[0]
  // el-upload 的 on-exceed 给的是原生 File；handleStart 需要带 uid 的 UploadRawFile
  if (file) uploadRef.value?.handleStart?.(file as UploadRawFile)
}

/** el-upload 的自定义上传：走 XHR 以便拿到上传进度 */
async function doStageUpload(options: UploadRequestOptions) {
  staging.value = true
  uploadPercent.value = 0
  fileError.value = ''
  try {
    const form = new FormData()
    form.append('file', options.file)
    form.append('strategy', strategy.value)
    const { data } = await useApi().uploadWithProgress<ArchiveReport>(STAGE_URL, form, {
      onProgress: (progress) => {
        uploadPercent.value = progress.percent
        options.onProgress?.({ percent: progress.percent } as UploadProgressEvent)
      },
    })
    report.value = data
    // 先让 el-upload 走完它的内部状态变更（会再触发一次 on-change），
    // 否则 nextTick 里的回调可能覆盖掉刚拿到的暂存状态
    options.onSuccess?.(data)
    stagedId.value = data.staged_id ?? ''
    stagedFileUid.value = options.file?.uid ?? null
    committed.value = false
    if (!stagedId.value) {
      // 防御：宁可报错，也不要出现“提示预检完成但无法确认导入”的迷惑状态
      fileError.value = '预检响应缺少 staged_id，请重试'
      ElMessage.error(fileError.value)
      return
    }
    const failed = data.totals.failed
    if (failed) ElMessage.warning(`预检完成，${failed} 篇有问题（见下方明细）`)
    else ElMessage.success('预检完成，请确认后导入')
  } catch (e) {
    fileError.value = errorMessage(e, '预检失败')
    report.value = null
    stagedId.value = ''
    options.onError?.(e as UploadErrorEvent)
    // 允许直接重试：把文件状态复位为 ready
    if (fileList.value[0]) fileList.value[0].status = 'ready'
  } finally {
    staging.value = false
  }
}

function startStage() {
  if (!fileList.value.length) {
    ElMessage.warning('请先选择 zip 压缩包')
    return
  }
  if (fileError.value) return
  // 允许对同一个文件重跑预检：submit() 只会提交 status=ready 的项
  const item = fileList.value[0]
  if (item && item.status !== 'ready') item.status = 'ready'
  uploadRef.value?.submit?.()
}

/** 策略变更：对已暂存的包重新预检（不重传文件） */
async function onStrategyChange() {
  if (!stagedId.value) return
  replanning.value = true
  try {
    const { data } = await useApi().post<ArchiveReport>(PLAN_URL, {
      staged_id: stagedId.value,
      strategy: strategy.value,
    })
    report.value = data
  } catch (e) {
    ElMessage.error(errorMessage(e, '重新预检失败'))
  } finally {
    replanning.value = false
  }
}

async function doCommit() {
  committing.value = true
  try {
    const { data } = await useApi().post<ArchiveReport>(COMMIT_URL, {
      staged_id: stagedId.value,
      strategy: strategy.value,
      auto_create_taxonomy: autoCreateTaxonomy.value,
      as_draft: asDraft.value,
    })
    report.value = data
    committed.value = true
    stagedId.value = '' // 已被消费
    ElMessage.success('导入完成')
    fetchArticles()
  } catch (e) {
    const status = (e as ApiError)?.status
    const hint =
      status === 429
        ? '导入过于频繁，请稍后再试'
        : status === 409
          ? '该暂存包已被执行或已过期，请重新上传'
          : status === 503
            ? '导入锁不可用（缓存/Redis 未就绪），请稍后重试'
            : errorMessage(e, '导入失败')
    ElMessage.error(hint)
  } finally {
    committing.value = false
  }
}

function downloadRollback() {
  const url = report.value?.rollback_package?.download_url
  if (url) useApi().openUrl(url)
}

function actionLabel(action: string): string {
  return (
    { create: '新建', update: '覆盖', skip: '跳过', failed: '失败' } as Record<string, string>
  )[action] ?? action
}
function actionType(action: string): 'success' | 'warning' | 'info' | 'danger' {
  return (
    { create: 'success', update: 'warning', skip: 'info', failed: 'danger' } as Record<
      string,
      'success' | 'warning' | 'info' | 'danger'
    >
  )[action] ?? 'info'
}
function skipReasonText(item: { skip_reason: string | null }): string {
  if (item.skip_reason === 'identical') return '内容完全相同'
  if (item.skip_reason === 'strategy') return '按策略跳过'
  return ''
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

          <el-button
            :disabled="!selectedIds.length || exporting"
            :loading="exporting"
            @click="doExport('selected')"
          >
            导出所选{{ selectedIds.length ? ` (${selectedIds.length})` : '' }}
          </el-button>
          <el-button
            :disabled="exporting"
            title="按当前筛选条件导出全部"
            @click="doExport('filtered')"
          >
            导出全部
          </el-button>
          <el-button @click="openImport">导入</el-button>

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
            <el-button
              v-if="articles.length"
              link
              type="primary"
              @click="toggleSelectAllOnPage"
            >
              {{ allSelectedOnPage ? '取消全选本页' : '全选本页' }}
            </el-button>
            <el-button type="warning" @click="goCreate">新建文章</el-button>
          </div>
        </div>
      </div>

      <div v-if="errorMsg" class="py-8 text-center text-sm text-red-500">{{ errorMsg }}</div>
      <template v-else>
        <div v-loading="loading" class="hidden overflow-x-auto md:block">
          <el-table
            ref="tableRef"
            :data="articles"
            row-key="id"
            border
            stripe
            :default-sort="{ prop: 'publish_time', order: 'descending' }"
            @sort-change="handleSortChange"
            @selection-change="handleSelectionChange"
          >
            <el-table-column type="selection" width="44" reserve-selection />
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
                {{ formatDateTime(row.publish_time) }}
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
              <div class="flex items-start gap-2">
                <el-checkbox
                  :model-value="isSelected(row.id)"
                  @change="toggleSelect(row.id)"
                />
                <h3 class="font-medium text-stone-900 dark:text-stone-100">{{ row.title }}</h3>
              </div>
              <el-tag :type="row.is_published ? 'success' : 'info'" size="small">
                {{ row.is_published ? '已发布' : '草稿' }}
              </el-tag>
            </div>
            <div class="mt-2 space-y-1 text-xs text-stone-500 dark:text-stone-400">
              <div>分类：{{ row.category?.name ?? '—' }}</div>
              <div>发布时间：{{ formatDateTime(row.publish_time) }}</div>
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

    <!-- 导入对话框 -->
    <el-dialog
      v-model="importVisible"
      title="导入文章归档包"
      width="min(820px, 94vw)"
      :close-on-click-modal="false"
      @close="resetImport"
    >
      <el-alert type="info" :closable="false" class="mb-4">
        <template #title>
          上传本系统导出的 zip（也可手工修改后上传）。流程：上传预检 → 确认导入；
          策略变更会重新预检，<b>不会重传文件</b>。
        </template>
      </el-alert>

      <el-upload
        ref="uploadRef"
        drag
        v-model:file-list="fileList"
        :auto-upload="false"
        :limit="1"
        accept=".zip"
        :http-request="doStageUpload"
        :on-change="onFileChange"
        :on-remove="onFileRemove"
        :on-exceed="onExceed"
        :disabled="staging || committing"
      >
        <div class="el-upload__text">
          将 zip 拖到此处，或 <em>点击选择文件</em>
        </div>
        <template #tip>
          <div class="el-upload__tip">
            仅支持 .zip；上限
            {{ limits ? formatBytes(limits.max_upload_bytes) : '1GB' }}；
            包内封面需为 jpg/png/webp，附件需为 pdf/doc/docx。
          </div>
        </template>
      </el-upload>

      <el-progress
        v-if="staging"
        class="mt-3"
        :percentage="uploadPercent"
        :stroke-width="14"
        striped
        striped-flow
      />

      <div v-if="fileError" class="mt-3 text-sm text-red-500">{{ fileError }}</div>

      <div class="mt-4 space-y-3">
        <el-radio-group
          v-model="strategy"
          :disabled="staging || committing || replanning"
          @change="onStrategyChange"
        >
          <el-radio-button value="skip">跳过已存在</el-radio-button>
          <el-radio-button value="update">覆盖更新</el-radio-button>
          <el-radio-button value="create_new">导入为新文章</el-radio-button>
        </el-radio-group>
        <div class="flex flex-wrap gap-x-6 gap-y-2">
          <el-checkbox v-model="autoCreateTaxonomy" :disabled="staging || committing">
            自动创建缺失的分类与标签
          </el-checkbox>
          <el-checkbox v-model="asDraft" :disabled="staging || committing">
            全部以草稿导入（仅对新建生效）
          </el-checkbox>
        </div>
        <div v-if="replanning" class="text-xs text-stone-500">正在按新策略重新预检…</div>
      </div>

      <div v-if="report" class="mt-5">
        <div class="mb-2 flex flex-wrap items-center gap-2 text-sm">
          <span class="text-stone-500">
            包内 {{ report.package.entries }} 个条目 /
            {{ formatBytes(report.package.bytes_uncompressed) }}
          </span>
          <el-tag size="small" type="success">新建 {{ report.totals.create }}</el-tag>
          <el-tag size="small" type="warning">覆盖 {{ report.totals.update }}</el-tag>
          <el-tag size="small" type="info">跳过 {{ report.totals.skip }}</el-tag>
          <el-tag v-if="report.totals.failed" size="small" type="danger">
            失败 {{ report.totals.failed }}
          </el-tag>
          <el-tag
            v-if="report.totals.categories_to_create.length"
            size="small"
            effect="plain"
          >
            将新建分类 {{ report.totals.categories_to_create.length }}
          </el-tag>
          <el-tag v-if="report.totals.tags_to_create.length" size="small" effect="plain">
            将新建标签 {{ report.totals.tags_to_create.length }}
          </el-tag>
        </div>

        <el-alert
          v-if="committed"
          :type="report.totals.failed ? 'warning' : 'success'"
          :closable="false"
          class="mb-3"
        >
          <template #title>
            导入完成：新建 {{ report.totals.create }}、覆盖 {{ report.totals.update }}、跳过
            {{ report.totals.skip }}、失败 {{ report.totals.failed }}。
          </template>
          <template #default>
            <span v-if="report.rollback_package">
              已生成回滚包（{{ report.rollback_package.count }} 篇，含覆盖前的内容）——
              <el-link type="primary" @click="downloadRollback">下载回滚包</el-link>
            </span>
          </template>
        </el-alert>

        <el-table :data="report.items" size="small" border max-height="280">
          <el-table-column label="文章" min-width="200">
            <template #default="{ row }: { row: any }">
              <div class="truncate text-stone-800 dark:text-stone-200">
                {{ row.title || row.slug || row.path }}
              </div>
              <div class="truncate text-xs text-stone-400">{{ row.path }}</div>
            </template>
          </el-table-column>
          <el-table-column label="动作" width="96">
            <template #default="{ row }: { row: any }">
              <el-tag size="small" :type="actionType(row.action)">
                {{ actionLabel(row.action) }}
              </el-tag>
              <div v-if="row.action === 'skip' && skipReasonText(row)" class="mt-1 text-xs text-stone-400">
                {{ skipReasonText(row) }}
              </div>
            </template>
          </el-table-column>
          <el-table-column label="警告 / 错误" min-width="240">
            <template #default="{ row }: { row: any }">
              <div v-for="err in row.errors" :key="err" class="text-xs text-red-500">
                ✕ {{ err }}
              </div>
              <div v-for="warn in row.warnings" :key="warn" class="text-xs text-amber-600">
                ! {{ warn }}
              </div>
              <span
                v-if="!row.errors.length && !row.warnings.length"
                class="text-xs text-stone-400"
              >
                —
              </span>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <template #footer>
        <el-button :disabled="committing" @click="importVisible = false">关闭</el-button>
        <el-button
          :loading="staging"
          :disabled="!fileList.length || staging || committing || !!fileError"
          @click="startStage"
        >
          上传并预检
        </el-button>
        <el-button
          type="warning"
          :loading="committing"
          :disabled="!stagedId || staging || replanning || committing"
          @click="doCommit"
        >
          确认导入
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>
