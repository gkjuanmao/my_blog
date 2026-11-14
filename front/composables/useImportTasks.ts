/**
 * 归档导入任务的前端单例状态 + 轮询。
 *
 * 为什么用**模块级** ref 而不是 `useState`/provide-inject：
 * 任务要跨组件共享（导入弹窗提交、任务页展示、layout 里弹通知），而且必须
 * 在弹窗关闭、切换页面后继续轮询。模块级单例天然满足，SSR 下也不会互相污染
 * （本模块只在客户端被调用，服务端渲染时不会有人 set timeout）。
 *
 * 轮询纪律：
 * - 用 `setTimeout` 串起来，不用 `setInterval` —— 慢响应不会叠加成并发请求；
 * - 页面不可见时暂停，回来后立刻补一次；
 * - 有终态就停；请求失败按 2s → 5s → 10s 退避，不让坏网络把后端打满。
 */
import type { ApiResponse, ImportTask, ImportTaskDetail, PaginatedResponse } from '~/types/api'

const TASKS_URL = '/admin/articles/import/tasks/'
/** 进行中的轮询间隔：任务页要看着数字跳，2s 足够 */
const POLL_MS = 2000
/** 退避序列（请求失败时用） */
const BACKOFF_MS = [2000, 5000, 10000]

const tasks = ref<ImportTask[]>([])
const loading = ref(false)
const error = ref('')

let timer: ReturnType<typeof setTimeout> | null = null
let failures = 0
/** 轮询期间的「静默刷新」不显示骨架屏，避免列表每次跳动 */
let silent = false

function isActive(task: ImportTask): boolean {
  return isTaskActive(task)
}

function merge(incoming: ImportTask[]): string[] {
  /** 返回本次新进入终态的任务 id（供 watcher 弹通知） */
  const previous = new Map(tasks.value.map(task => [task.id, task.status]))
  tasks.value = incoming
  return incoming
    .filter(task => !isActive(task) && previous.get(task.id) && previous.get(task.id) !== task.status)
    .map(task => task.id)
}

const activeTasks = computed(() => tasks.value.filter(isActive))
const activeCount = computed(() => activeTasks.value.length)

/** 有新任务进入终态时 +1，页面可 watch 它刷新文章列表 */
const finishedTick = ref(0)

async function fetchTasks(opts: { quiet?: boolean } = {}): Promise<string[]> {
  if (!opts.quiet) loading.value = true
  try {
    // 只取第一页：任务页也只需要最近 20 条（更早的看详情或翻页自己查）
    const { data } = await useApi().get<PaginatedResponse<ImportTask>>(TASKS_URL, { page_size: 20 })
    error.value = ''
    failures = 0
    return merge(data.items)
  } catch (e) {
    error.value = errorMessage(e, '任务列表加载失败')
    failures = Math.min(failures + 1, BACKOFF_MS.length - 1)
    return []
  } finally {
    if (!opts.quiet) loading.value = false
  }
}

function stopPolling(): void {
  if (timer) clearTimeout(timer)
  timer = null
}

function schedule(delay: number): void {
  stopPolling()
  if (!import.meta.client) return
  timer = setTimeout(async () => {
    timer = null
    if (document.hidden) {
      // 页面不可见就暂停，回到前台时由 visibilitychange 唤醒
      return
    }
    const finished = await fetchTasks({ quiet: silent })
    if (finished.length) finishedTick.value += 1
    tick()
  }, delay)
}

/** 按当前状态决定是否继续轮询 */
function tick(): void {
  if (activeCount.value === 0) {
    stopPolling()
    return
  }
  schedule(failures ? BACKOFF_MS[failures] : POLL_MS)
}

/**
 * 启动轮询（幂等）。
 *
 * @param opts.silent 为 true 时后续请求不显示 loading（弹窗提交后即可静默跟进）
 */
async function startPolling(opts: { silent?: boolean } = {}): Promise<void> {
  silent = opts.silent ?? true
  const finished = await fetchTasks({ quiet: silent })
  if (finished.length) finishedTick.value += 1
  tick()
}

/** 手动刷新一次（列表页点刷新、或从详情回来后） */
async function refresh(): Promise<void> {
  const finished = await fetchTasks()
  if (finished.length) finishedTick.value += 1
  tick()
}

async function fetchDetail(taskId: string): Promise<ImportTaskDetail | null> {
  try {
    const { data } = await useApi().get<ImportTaskDetail>(`${TASKS_URL}${taskId}/`)
    return data
  } catch (e) {
    error.value = errorMessage(e, '任务详情加载失败')
    return null
  }
}

/** 取消排队中的任务（后端只允许 queued，执行中会 409） */
async function cancelTask(taskId: string): Promise<boolean> {
  try {
    await useApi().post(`${TASKS_URL}${taskId}/cancel/`)
    await refresh()
    return true
  } catch (e) {
    error.value = errorMessage(e, '取消失败')
    return false
  }
}

/** 入队后把返回的任务塞进列表（不必等下一轮轮询） */
function pushTask(task: ImportTask): void {
  const rest = tasks.value.filter(item => item.id !== task.id)
  tasks.value = [task, ...rest]
}

let visibilityBound = false
function bindVisibility(): void {
  if (visibilityBound || !import.meta.client) return
  visibilityBound = true
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      stopPolling()
      return
    }
    if (activeCount.value > 0) void startPolling({ silent: true })
  })
}

export function useImportTasks() {
  bindVisibility()
  return {
    tasks,
    activeTasks,
    activeCount,
    finishedTick,
    loading,
    error,
    startPolling,
    stopPolling,
    refresh,
    fetchDetail,
    cancelTask,
    pushTask,
  }
}

export type { ImportTask }
export type TaskApiList = ApiResponse<PaginatedResponse<ImportTask>>
