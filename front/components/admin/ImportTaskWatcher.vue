<script setup lang="ts">
/**
 * 导入任务通知器（无 UI，挂在 admin layout 里）。
 *
 * 为什么必须在 layout 而不是导入弹窗里：任务跑完之后用户很可能已经关掉弹窗、
 * 甚至切到了别的后台页面。放在 layout 才能保证「任务完成 → 右下角提示」在任何
 * 后台页面上都能出现；弹窗与任务页共用同一份单例状态，不会重复轮询。
 *
 * 通知用 ElNotification（默认就是右下角 + 可设 duration），10s 自动关闭，
 * 点一下跳任务页看明细。
 */
import type { ImportTask } from '~/types/api'

const { tasks, finishedTick, startPolling } = useImportTasks()

/** 已经提示过的任务（首次加载时把历史任务记为已提示，避免刷新页面炸出一串通知） */
const notified = new Set<string>()
let primed = false

function notify(task: ImportTask) {
  const to = '/administrator/tasks'
  if (task.status === 'succeeded') {
    const failed = task.progress.failed
    ElNotification({
      title: failed ? `导入完成，${failed} 篇失败` : '导入完成',
      message: `${taskResultSummary(task)}。点击查看任务详情。`,
      type: failed ? 'warning' : 'success',
      position: 'bottom-right',
      duration: 10000,
      customClass: 'ad-task-toast',
      onClick: () => void navigateTo(to),
    })
    return
  }
  if (task.status === 'failed') {
    ElNotification({
      title: '导入失败',
      message: `${task.error?.message ?? '未知原因'}\n${task.error?.hint ?? ''}`.trim(),
      type: 'error',
      position: 'bottom-right',
      duration: 10000,
      customClass: 'ad-task-toast',
      onClick: () => void navigateTo(to),
    })
    return
  }
  if (task.status === 'canceled') {
    ElNotification({
      title: '导入任务已取消',
      message: '未执行任何导入。',
      type: 'info',
      position: 'bottom-right',
      duration: 10000,
      customClass: 'ad-task-toast',
      onClick: () => void navigateTo(to),
    })
  }
}

function prime(list: ImportTask[]) {
  for (const task of list) {
    if (task.status !== 'queued' && task.status !== 'running') notified.add(task.id)
  }
  primed = true
}

watch(
  tasks,
  (list) => {
    if (!primed) {
      // 首次拿到列表：历史终态任务只登记、不弹窗
      if (list.length) prime(list)
      return
    }
    for (const task of list) {
      if (notified.has(task.id)) continue
      if (task.status === 'queued' || task.status === 'running') continue
      notified.add(task.id)
      notify(task)
    }
  },
  { deep: true },
)

// finishedTick 变化意味着「本轮轮询里有任务刚结束」，同样由上面的 watch 兜住；
// 这里只负责在挂载时把轮询接上（若已有任务在跑，进后台任何页面都能收到通知）。
onMounted(() => {
  void startPolling({ silent: true })
})

onUnmounted(() => {
  // 不 stopPolling：切页面时 layout 不销毁，任务还在跑就不该停。
})
</script>

<template>
  <span class="ad-sr" aria-live="polite">
    {{ finishedTick ? '有导入任务刚刚结束' : '' }}
  </span>
</template>
