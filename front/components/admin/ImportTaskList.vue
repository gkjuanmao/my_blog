<script setup lang="ts">
/**
 * 导入任务台账：列表 + 右侧详情抽屉。
 *
 * 状态口径由后端给（queued/running/succeeded/failed/canceled），前端只负责呈现；
 * 「排队中还有个位置」这类信息不本地推算——队列深度只有服务端知道。
 *
 * 两个刻意选择：
 * 1. 进度条对终态任务显示 100%（失败/取消也算「结束了」），不显示成 0% 的半截条；
 * 2. 回滚包文案写死「仅还原到本任务执行前一刻」——同一篇文章多次覆盖时，
 *    回滚包必须按任务完成时间**倒序**回退，正序会把结果互相盖掉。
 */
import type { ArchiveReport, ImportTask, ImportTaskDetail } from '~/types/api'
import { formatRelativeTime } from '~/utils/date'
import { formatBytes } from '~/utils/format'

const { tasks, loading, error, refresh, fetchDetail, cancelTask } = useImportTasks()

const detailOpen = ref(false)
const detail = ref<ImportTaskDetail | null>(null)
const detailLoading = ref(false)
const detailError = ref('')

const filter = ref<'all' | 'active' | 'failed'>('all')

const filtered = computed(() => {
  if (filter.value === 'active') {
    return tasks.value.filter(task => task.status === 'queued' || task.status === 'running')
  }
  if (filter.value === 'failed') {
    return tasks.value.filter(task => task.status === 'failed')
  }
  return tasks.value
})

const queueTotal = computed(() => tasks.value.find(t => t.queue_total)?.queue_total ?? 0)
const queueTotalHint = computed(() => queueHint({ queue_total: queueTotal.value }))

const meta = computed(() => {
  const active = tasks.value.filter(t => t.status === 'queued' || t.status === 'running').length
  const failed = tasks.value.filter(t => t.status === 'failed').length
  return `${tasks.value.length} 条任务 · ${active} 个进行中 · ${failed} 个失败`
})

function statusLabel(task: ImportTask): string {
  return {
    queued: '排队中',
    running: '执行中',
    succeeded: '已完成',
    failed: '失败',
    canceled: '已取消',
  }[task.status]
}

function statusClass(task: ImportTask): string {
  return {
    queued: 'ad-status--wait',
    running: 'ad-status--run',
    succeeded: '',
    failed: 'ad-status--bad',
    canceled: 'ad-status--draft',
  }[task.status]
}

function strategyLabel(task: ImportTask): string {
  return { skip: '跳过已存在', update: '覆盖更新', create_new: '导入为新文章' }[task.strategy]
}

const durationText = (task: ImportTask) => taskDurationText(task.duration_ms)
const percentOf = (task: ImportTask) => taskPercent(task)

/** 详情里的报告（只在成功任务上有内容） */
const report = computed<ArchiveReport | null>(() => {
  const value = detail.value?.report as ArchiveReport | undefined
  return value && Array.isArray(value.items) ? value : null
})

/** 预检 vs 实况的差异（排队期间前置任务改变了数据时出现） */
const drift = computed(() => report.value?.plan_drift ?? null)

function driftSummary(): string {
  return driftText(drift.value?.changed)
}

async function openDetail(task: ImportTask) {
  detailOpen.value = true
  detailLoading.value = true
  detailError.value = ''
  detail.value = null
  const data = await fetchDetail(task.id)
  if (!data) detailError.value = '任务详情加载失败'
  detail.value = data
  detailLoading.value = false
}

async function cancel(task: ImportTask) {
  const ok = await cancelTask(task.id)
  ElMessage[ok ? 'success' : 'error'](ok ? '已取消' : error.value || '取消失败')
}

function downloadRollback(task: ImportTask | null) {
  const url = task?.rollback_package?.download_url
  if (url) useApi().openUrl(url)
}

onMounted(() => {
  void refresh()
})
</script>

<template>
  <div class="ad-page">
    <AdminMasthead eyebrow="任务" eyebrow-en="Tasks" title="导入任务" :meta="meta">
      <template #actions>
        <button class="ad-btn ad-btn--ghost" type="button" :disabled="loading" @click="refresh">
          <AdminIcon name="refresh" :size="14" />刷新
        </button>
      </template>
    </AdminMasthead>

    <div class="ad-toolbar">
      <div class="ad-segs" role="group" aria-label="按状态筛选">
        <button class="ad-seg" type="button" :aria-pressed="filter === 'all'" @click="filter = 'all'">
          全部
        </button>
        <button class="ad-seg" type="button" :aria-pressed="filter === 'active'" @click="filter = 'active'">
          进行中
        </button>
        <button class="ad-seg" type="button" :aria-pressed="filter === 'failed'" @click="filter = 'failed'">
          失败
        </button>
      </div>

      <span v-if="queueTotal" class="ad-toolbar__note">{{ queueTotalHint }}</span>
      <span class="ad-toolbar__spacer" />
      <span class="ad-toolbar__note">{{ filtered.length }} 条</span>
    </div>

    <p v-if="error" class="ad-note ad-note--bad" style="padding: 12px var(--ad-gutter) 0">
      {{ error }}
    </p>

    <div class="ad-tablearea">
      <table class="ad-table ad-table--acts">
        <caption class="ad-sr">
          导入任务列表，共 {{ filtered.length }} 条
        </caption>
        <thead>
          <tr>
            <th>任务</th>
            <th style="width: 156px">状态</th>
            <th style="width: 168px">进度</th>
            <th class="ad-col-md" style="width: 210px">结果</th>
            <th class="ad-col-md num r" style="width: 96px">耗时</th>
            <th style="width: 110px"><span class="ad-sr">操作</span></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="task in filtered" :key="task.id">
            <td>
              <p class="ad-t-title">{{ strategyLabel(task) }}</p>
              <span class="ad-t-sub">
                {{ task.id.slice(0, 8) }} · {{ task.username || '—' }} ·
                {{ formatRelativeTime(task.created_at) }}
              </span>
            </td>
            <td>
              <span class="ad-status" :class="statusClass(task)">
                <i aria-hidden="true" />
                {{ statusLabel(task) }}
              </span>
              <div v-if="task.status === 'running' || task.status === 'queued'" class="ad-t-sub">
                {{ taskStatusText(task) }}
              </div>
              <div v-else-if="task.status === 'failed'" class="ad-t-sub">
                {{ task.error?.message }}
              </div>
            </td>
            <td>
              <div class="ad-taskbar" :title="`${task.progress.processed}/${task.progress.total}`">
                <i
                  :style="{ width: `${percentOf(task)}%` }"
                  :class="{ 'is-bad': task.status === 'failed' }"
                />
              </div>
              <span class="ad-t-sub">{{ task.progress.processed }}/{{ task.progress.total || '—' }}</span>
            </td>
            <td class="ad-col-md">
              <span class="ad-table__date">{{ taskResultSummary(task) }}</span>
            </td>
            <td class="num r ad-col-md">{{ durationText(task) }}</td>
            <td class="ad-table__acts">
              <button class="ad-link" type="button" @click="openDetail(task)">详情</button>
              <button
                v-if="task.status === 'queued'"
                class="ad-link ad-link--danger"
                type="button"
                @click="cancel(task)"
              >
                取消
              </button>
            </td>
          </tr>
        </tbody>
      </table>

      <div v-if="!filtered.length" class="ad-void">
        <p>{{ loading ? '正在加载任务…' : '这里还没有导入任务。' }}</p>
        <span>从「文章 → 导入归档」提交后，记录会出现在这里</span>
      </div>
      <div v-else class="ad-void">
        <p>队列串行执行，一次只跑一个导入任务。</p>
        <span>失败的任务不会中断已写入的部分，回滚包可在详情里下载</span>
      </div>
    </div>

    <div class="ad-footbar">
      <span>共 {{ filtered.length }} 条 · 保留最近 30 天</span>
      <span class="ad-toolbar__spacer" />
      <span>回滚包保留 7 天</span>
    </div>

    <el-drawer v-model="detailOpen" title="导入任务详情" size="min(480px, 94vw)">
      <div v-if="detailLoading" class="ad-note">正在加载…</div>
      <p v-else-if="detailError" class="ad-note ad-note--bad">{{ detailError }}</p>
      <div v-else-if="detail" class="ad-taskdetail">
        <dl class="ad-kv">
          <div><dt>任务号</dt><dd>{{ detail.id }}</dd></div>
          <div><dt>状态</dt><dd>{{ statusLabel(detail) }}</dd></div>
          <div><dt>策略</dt><dd>{{ strategyLabel(detail) }}</dd></div>
          <div><dt>提交人</dt><dd>{{ detail.username || '—' }}</dd></div>
          <div><dt>提交时间</dt><dd>{{ formatRelativeTime(detail.created_at) }}</dd></div>
          <div><dt>耗时</dt><dd>{{ durationText(detail) }}</dd></div>
          <div><dt>包体积</dt><dd>{{ detail.package.bytes ? formatBytes(detail.package.bytes) : '—' }}</dd></div>
          <div><dt>条目数</dt><dd>{{ detail.package.entries ?? '—' }}</dd></div>
        </dl>

        <el-alert
          v-if="detail.status === 'failed'"
          class="mt-4"
          type="error"
          :closable="false"
          show-icon
        >
          <template #title>{{ detail.error?.message }}</template>
          <template #default>
            <p>{{ detail.error?.hint }}</p>
          </template>
        </el-alert>

        <el-alert v-if="drift" class="mt-4" type="warning" :closable="false" show-icon>
          <template #title>{{ drift.message }}</template>
          <template #default>
            <p>{{ driftSummary() }}</p>
          </template>
        </el-alert>

        <p v-if="detail.rollback_package" class="ad-note mt-4">
          已生成回滚包（{{ detail.rollback_package.count }} 篇，仅还原到本任务执行前一刻的状态）——
          <button class="ad-link" type="button" @click="downloadRollback(detail)">
            下载回滚包
          </button>
        </p>

        <div v-if="report" class="mt-5">
          <div class="mb-2 flex flex-wrap items-center gap-2 text-sm">
            <el-tag size="small" type="success">新建 {{ report.totals.create }}</el-tag>
            <el-tag size="small" type="warning">覆盖 {{ report.totals.update }}</el-tag>
            <el-tag size="small" type="info">跳过 {{ report.totals.skip }}</el-tag>
            <el-tag v-if="report.totals.failed" size="small" type="danger">
              失败 {{ report.totals.failed }}
            </el-tag>
          </div>
          <el-table :data="report.items" size="small" border max-height="360">
            <el-table-column label="文章" min-width="180">
              <template #default="{ row }">
                <div class="truncate">{{ row.title || row.slug || row.path }}</div>
                <div class="truncate text-xs text-stone-400">{{ row.path }}</div>
              </template>
            </el-table-column>
            <el-table-column label="动作" width="88">
              <template #default="{ row }">
                <el-tag
                  size="small"
                  :type="
                    ({ create: 'success', update: 'warning', skip: 'info', failed: 'danger' } as Record<string, 'success' | 'warning' | 'info' | 'danger'>)[
                      row.action
                    ] ?? 'info'
                  "
                >
                  {{ ({ create: '新建', update: '覆盖', skip: '跳过', failed: '失败' } as Record<string, string>)[row.action] ?? row.action }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="警告 / 错误" min-width="220">
              <template #default="{ row }">
                <div v-for="err in row.errors" :key="err" class="text-xs text-red-500">
                  ✕ {{ err }}
                </div>
                <div v-for="warn in row.warnings" :key="warn" class="text-xs text-amber-600">
                  ! {{ warn }}
                </div>
                <span v-if="!row.errors.length && !row.warnings.length" class="text-xs text-stone-400">
                  —
                </span>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>
    </el-drawer>
  </div>
</template>
