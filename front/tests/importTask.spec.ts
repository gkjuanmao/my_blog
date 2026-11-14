import { describe, expect, it } from 'vitest'

import type { ImportTask } from '../types/api'
import {
  actionLabel,
  driftText,
  isTaskActive,
  taskDurationText,
  taskErrorText,
  taskPercent,
  taskResultSummary,
  taskStatusText,
} from '../utils/importTask'

function makeTask(patch: Partial<ImportTask> = {}): ImportTask {
  return {
    id: 'a1',
    status: 'queued',
    phase: 'waiting',
    phase_label: '',
    strategy: 'skip',
    auto_create_taxonomy: true,
    as_draft: false,
    progress: { total: 0, processed: 0, create: 0, update: 0, skip: 0, failed: 0, percent: 0 },
    preview: {},
    package: {},
    created_at: '2026-11-14T10:00:00+08:00',
    started_at: null,
    finished_at: null,
    duration_ms: null,
    username: 'gkjuanmao',
    error: null,
    rollback_package: null,
    warning: null,
    queue_position: 1,
    queue_total: 1,
    attempts: 1,
    ...patch,
  }
}

describe('importTask utils', () => {
  it('只有 queued/running 算进行中（决定是否继续轮询）', () => {
    expect(isTaskActive(makeTask({ status: 'queued' }))).toBe(true)
    expect(isTaskActive(makeTask({ status: 'running' }))).toBe(true)
    expect(isTaskActive(makeTask({ status: 'succeeded' }))).toBe(false)
    expect(isTaskActive(makeTask({ status: 'failed' }))).toBe(false)
    expect(isTaskActive(makeTask({ status: 'canceled' }))).toBe(false)
  })

  it('终态进度条一律 100%，进行中才用后端百分比', () => {
    const running = makeTask({
      status: 'running',
      progress: { total: 10, processed: 4, create: 4, update: 0, skip: 0, failed: 0, percent: 40 },
    })
    expect(taskPercent(running)).toBe(40)

    const failed = makeTask({
      status: 'failed',
      progress: { total: 10, processed: 4, create: 0, update: 0, skip: 0, failed: 4, percent: 40 },
    })
    // 失败也是「结束了」，显示 40% 会让人以为还在后台跑
    expect(taskPercent(failed)).toBe(100)
    expect(taskPercent(makeTask({ status: 'canceled' }))).toBe(100)
  })

  it('排队时带队列位置，执行中用后端 phase_label', () => {
    expect(taskStatusText(makeTask({ status: 'queued', queue_position: 1 }))).toBe('排队中')
    expect(taskStatusText(makeTask({ status: 'queued', queue_position: 3 }))).toBe(
      '排队中（前面还有 2 个）',
    )
    // 被锁冲突推迟时后端给的 phase_label 更有信息量，优先显示
    expect(
      taskStatusText(
        makeTask({ status: 'queued', queue_position: 1, phase_label: '等待前一个导入结束（第 2 次重试）' }),
      ),
    ).toBe('等待前一个导入结束（第 2 次重试）')
    // 位置缺失（不在排队中）时也不能出现「前面还有 -1 个」
    expect(taskStatusText(makeTask({ status: 'queued', queue_position: null }))).toBe('排队中')
    expect(taskStatusText(makeTask({ status: 'running', phase_label: '写入文章 42/180' }))).toBe(
      '写入文章 42/180',
    )
    // phase_label 缺失时不留空白
    expect(taskStatusText(makeTask({ status: 'running', phase_label: '' }))).toBe('执行中')
  })

  it('结果摘要只在有失败时追加失败数', () => {
    expect(
      taskResultSummary({
        progress: { total: 6, processed: 6, create: 3, update: 1, skip: 2, failed: 0, percent: 100 },
      }),
    ).toBe('新建 3 · 覆盖 1 · 跳过 2')
    expect(
      taskResultSummary({
        progress: { total: 3, processed: 3, create: 1, update: 0, skip: 0, failed: 2, percent: 100 },
      }),
    ).toBe('新建 1 · 覆盖 0 · 跳过 0 · 失败 2')
  })

  it('耗时按 60s 分档，缺值显示破折号', () => {
    expect(taskDurationText(null)).toBe('—')
    expect(taskDurationText(0)).toBe('—')
    expect(taskDurationText(8200)).toBe('8s')
    expect(taskDurationText(150000)).toBe('2m 30s')
  })

  it('漂移文案把「预检 → 实况」逐项列出（排队期间数据变化的唯一解释）', () => {
    expect(
      driftText({
        create: { preview: 50, actual: 20 },
        skip: { preview: 3, actual: 33 },
      }),
    ).toBe('新建 50 → 20、跳过 3 → 33')
    expect(driftText(undefined)).toBe('')
    expect(driftText({})).toBe('')
  })

  it('失败文案同时给原因与指引，缺一项都让人无从下手', () => {
    expect(
      taskErrorText(
        makeTask({
          status: 'failed',
          error: { code: 'worker_lost', message: '任务被中断', hint: '用回滚包还原后再导' },
        }),
      ),
    ).toBe('任务被中断\n用回滚包还原后再导')
    expect(taskErrorText(makeTask())).toBe('')
  })

  it('未知名动作原样透出，不吞成空白', () => {
    expect(actionLabel('create')).toBe('新建')
    expect(actionLabel('whatever')).toBe('whatever')
  })
})
