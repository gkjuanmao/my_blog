/**
 * 导入任务的纯展示逻辑（无 Vue 依赖，便于单测）。
 *
 * 抽出来的原因：这些口径在任务列表、详情抽屉、右下角通知三处都要用，
 * 各写一套必然漂移——比如「失败任务进度条该显示 100% 还是 0%」这种判断，
 * 只在通知里对、在列表里错，是很难发现的不一致。
 */
import type { ImportTask, ImportTaskStatus } from '~/types/api'

const ACTIVE: ImportTaskStatus[] = ['queued', 'running']

/** 任务是否还在进行（决定要不要继续轮询） */
export function isTaskActive(task: Pick<ImportTask, 'status'>): boolean {
  return ACTIVE.includes(task.status)
}

/**
 * 进度条百分比。
 *
 * 终态一律 100%：失败/取消也是「结束了」，显示成半截条会让人以为还在后台跑。
 */
export function taskPercent(task: Pick<ImportTask, 'status' | 'progress'>): number {
  if (task.status === 'succeeded' || task.status === 'failed' || task.status === 'canceled') {
    return 100
  }
  return task.progress.percent
}

/** 状态文案（排队时附带队列位置，执行中直接用后端的 phase_label） */
export function taskStatusText(task: ImportTask): string {
  switch (task.status) {
    case 'queued':
      return task.queue_position > 1 ? `排队中（前面还有 ${task.queue_position - 1} 个）` : '排队中'
    case 'running':
      return task.phase_label || '执行中'
    case 'succeeded':
      return '已完成'
    case 'failed':
      return '失败'
    case 'canceled':
      return '已取消'
  }
}

/** 结果摘要：`新建 3 · 覆盖 1 · 跳过 2`，失败数有值才追加（避免遍地 0） */
export function taskResultSummary(task: Pick<ImportTask, 'progress'>): string {
  const { create, update, skip, failed } = task.progress
  const parts = [`新建 ${create}`, `覆盖 ${update}`, `跳过 ${skip}`]
  if (failed) parts.push(`失败 ${failed}`)
  return parts.join(' · ')
}

/** 耗时文案：`8s` / `2m 30s` / `—` */
export function taskDurationText(durationMs: number | null | undefined): string {
  if (!durationMs) return '—'
  const seconds = Math.round(durationMs / 1000)
  if (seconds < 60) return `${seconds}s`
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
}

const ACTION_LABELS: Record<string, string> = {
  create: '新建',
  update: '覆盖',
  skip: '跳过',
  failed: '失败',
}

export function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action
}

/**
 * 「预检 vs 实况」差异文案：`新建 50 → 20、跳过 3 → 33`
 *
 * 排队期间前置任务会改变数据库，用户在提交前看到的预检数字可能与执行结果不同。
 * 这个差异必须显式说明，否则用户会认为「导入没生效」。
 */
export function driftText(
  changed: Record<string, { preview: number; actual: number }> | undefined,
): string {
  if (!changed) return ''
  return Object.entries(changed)
    .map(([key, value]) => `${ACTION_LABELS[key] ?? key} ${value.preview} → ${value.actual}`)
    .join('、')
}

/**
 * 失败文案（通知与详情共用）：原因 + 指引，缺一个都会让人无从下手。
 */
export function taskErrorText(task: Pick<ImportTask, 'error'>): string {
  if (!task.error) return ''
  return [task.error.message, task.error.hint].filter(Boolean).join('\n')
}
