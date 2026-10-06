/**
 * 「简单资源」（分类 / 标签）列表 + 增删改的**数据层**（FE-10）。
 *
 * 界面的本地状态（弹窗开关、正在编辑的行、表单值、保存中、删除确认）在
 * `components/admin/ResourceCrudTable.vue` 里；这里只负责列表加载与两个写请求，
 * 两者合起来取代了 `categories.vue` / `tags.vue` 原先 1:1 复制的两份实现。
 */
import type { Ref } from 'vue'

/** 可被本 composable 管理的行：都有 id / name / slug，描述可选 */
export interface CrudRow {
  id: number
  name: string
  slug: string
  description?: string
}

/** 表格列声明（驱动 el-table 的列） */
export interface CrudColumn {
  prop: string
  label: string
  width?: string
}

/** 表单字段声明（第一项为必填项） */
export interface CrudField {
  key: string
  label: string
  placeholder?: string
}

export interface CrudTableOptions {
  /** 公开列表接口，如 `/categories/` */
  listUrl: string
  /** 管理端 CRUD 基础路径，如 `/admin/categories`（不带结尾斜杠） */
  baseUrl: string
}

export function useCrudTable(options: CrudTableOptions) {
  const api = useApi()

  const list = ref([]) as Ref<CrudRow[]>
  const loading = ref(false)

  async function fetchList() {
    loading.value = true
    try {
      const { data } = await api.get<CrudRow[]>(options.listUrl)
      list.value = data
    } catch (e) {
      ElMessage.error(errorMessage(e, '加载失败'))
    } finally {
      loading.value = false
    }
  }

  /** 新增（editing 为 null）或更新；写请求失败时抛给调用方展示错误 */
  async function submit(payload: Record<string, string>, editing: CrudRow | null) {
    await (editing
      ? api.put(`${options.baseUrl}/${editing.id}/`, payload)
      : api.post(`${options.baseUrl}/`, payload))
  }

  async function remove(row: CrudRow) {
    await api.del(`${options.baseUrl}/${row.id}/`)
  }

  return { list, loading, fetchList, submit, remove }
}