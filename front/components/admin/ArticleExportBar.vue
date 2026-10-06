<script setup lang="ts">
/**
 * 导出按钮组（FE-09 从 `pages/administrator/articles/index.vue` 拆出）。
 *
 * 两个按钮 + 预估/确认/取票据/触发下载的流程都在这一个组件内，页面只需把当前的
 * 筛选值与勾选传进来。渲染为**多个根节点**，可直接嵌进页面的工具栏 flex 行。
 */
import type { ArchiveEstimate, ArchiveExportTicket } from '~/types/api'
import { formatBytes } from '~/utils/format'

const props = defineProps<{
  /** 当前筛选值（按筛选导出时使用） */
  keyword: string
  categorySlug: string
  status: string
  /** 当前勾选的文章 id（导出所选时使用） */
  selectedIds: number[]
}>()

const exporting = ref(false)

/** 只取非空筛选条件作为导出参数 */
function filterParams(): Record<string, unknown> {
  const params: Record<string, unknown> = {}
  if (props.keyword.trim()) params.keyword = props.keyword.trim()
  if (props.categorySlug) params.category_slug = props.categorySlug
  if (props.status) params.is_published = props.status
  return params
}

async function doExport(scope: 'selected' | 'filtered') {
  if (scope === 'selected' && props.selectedIds.length === 0) {
    ElMessage.warning('请先勾选要导出的文章')
    return
  }
  const params =
    scope === 'selected' ? { ids: props.selectedIds.join(',') } : filterParams()

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
</script>

<template>
  <el-button
    :disabled="!selectedIds.length || exporting"
    :loading="exporting"
    @click="doExport('selected')"
  >
    导出所选{{ selectedIds.length ? ` (${selectedIds.length})` : '' }}
  </el-button>
  <el-button :disabled="exporting" title="按当前筛选条件导出全部" @click="doExport('filtered')">
    导出全部
  </el-button>
</template>