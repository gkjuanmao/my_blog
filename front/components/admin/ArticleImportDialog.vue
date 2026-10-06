<script setup lang="ts">
/**
 * 归档导入对话框（FE-09 从 `pages/administrator/articles/index.vue` 拆出）。
 *
 * 自包含：上传/预检/重新预检/提交的整套状态与请求都在这里，页面只需
 * `v-model` 控制开关，并在 `imported` 事件里刷新列表。
 */
import type {
  UploadFile,
  UploadInstance,
  UploadProgressEvent,
  UploadRawFile,
  UploadRequestOptions,
  UploadUserFile,
} from 'element-plus'

import type { ApiError, ArchiveLimits, ArchiveReport, ArchiveStrategy } from '~/types/api'
import { formatBytes } from '~/utils/format'

/** el-upload 的 onError 回调参数类型（element-plus 未从根导出该类型） */
type UploadErrorEvent = Parameters<NonNullable<UploadRequestOptions['onError']>>[0]

const STAGE_URL = '/admin/articles/import/stage/'
const PLAN_URL = '/admin/articles/import/plan/'
const COMMIT_URL = '/admin/articles/import/commit/'

const visible = defineModel<boolean>({ required: true })

const emit = defineEmits<{
  /** 导入成功（未被消费的暂存包不退；页面据此刷新列表） */
  imported: []
}>()

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

// 每次打开都复位，并（首次）取一次上限配置
watch(visible, (open) => {
  if (!open) return
  resetImport()
  if (!limits.value) fetchLimits()
})

async function fetchLimits() {
  try {
    const { data } = await useApi().get<ArchiveLimits>('/admin/articles/import/limits/')
    limits.value = data
  } catch {
    limits.value = null
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
    emit('imported')
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
</script>

<template>
  <el-dialog
    v-model="visible"
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
      v-model:file-list="fileList"
      drag
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
      <el-button :disabled="committing" @click="visible = false">关闭</el-button>
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
</template>