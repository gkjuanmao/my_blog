/**
 * 把列表分页状态（页码 / 每页条数）同步到 URL query，使浏览器后退 / 刷新 / 分享链接
 * 都能回到原来的页。只负责 query 读写，不含拉取、筛选等业务逻辑（交由各页面自理）。
 */
export function usePageQuery(defaultPageSize = 10) {
  const route = useRoute()
  const router = useRouter()

  /** 解析 URL 中的正整数，非法（缺省 / 数组 / 非数字 / 小于 1）返回 null */
  function parsePositiveInt(raw: unknown): number | null {
    const value = Array.isArray(raw) ? raw[0] : raw
    if (typeof value !== 'string' || value.trim() === '') return null
    const n = Number(value)
    return Number.isInteger(n) && n >= 1 ? n : null
  }

  /** 归一化外部传入的值，非法时回落到 fallback */
  function normalize(value: unknown, fallback: number): number {
    const n = typeof value === 'number' ? value : Number(value)
    return Number.isFinite(n) && n >= 1 ? Math.floor(n) : fallback
  }

  const page = computed({
    get: () => parsePositiveInt(route.query.page) ?? 1,
    set: (value: number) => {
      const next = normalize(value, 1)
      if (next === (parsePositiveInt(route.query.page) ?? 1)) return
      const query = { ...route.query }
      // 第 1 页不写 query，保持 URL 干净
      if (next <= 1) delete query.page
      else query.page = String(next)
      router.replace({ query })
    },
  })

  const pageSize = computed({
    get: () => parsePositiveInt(route.query.page_size) ?? defaultPageSize,
    set: (value: number) => {
      const next = normalize(value, defaultPageSize)
      if (next === (parsePositiveInt(route.query.page_size) ?? defaultPageSize)) return
      // 每页条数变化时一并回到第 1 页，保证一次导航完成，避免中间态多拉一次
      const query: typeof route.query = { ...route.query }
      query.page_size = String(next)
      delete query.page
      router.replace({ query })
    },
  })

  /**
   * 数据返回后校正越界页码（如文章被删导致总页数变少）。
   * SSR 阶段不触发导航，交由客户端挂载后修正。
   */
  function clampPage(total: number, size: number): void {
    if (!import.meta.client) return
    const lastPage = Math.max(1, Math.ceil(total / size))
    if (lastPage < page.value) page.value = lastPage
  }

  return { page, pageSize, clampPage }
}