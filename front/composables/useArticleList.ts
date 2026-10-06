/**
 * 文章列表页共用的加载逻辑（FE-11）。
 *
 * 公开列表页（首页 / 分类 / 标签 / 搜索）与后台文章列表原本各自复制了同一套：
 * 分页状态、竞态守卫、越界页码收敛、错误文案。这里收敛成一处，页面只提供
 * 「怎么取这一页数据」的 loader（各自带过滤参数，或顺带请求分类/标签实体）。
 *
 * 渲染侧见 `components/ArticleListSection.vue`（首页/分类/标签三页的三态与分页）
 * 与 `components/ArticleGrid.vue`（公开页共用的卡片网格）；后台列表用
 * `components/admin/ArticleListTable.vue` / `ArticleMobileCards.vue`。
 */
import type { Article, PaginatedResponse } from '~/types/api'

export function useArticleList(options: { fallbackMessage?: string } = {}) {
  const { page, pageSize, clampPage } = usePageQuery()
  const guard = useRequestGuard()

  const articles = ref([]) as Ref<Article[]>
  const total = ref(0)
  const loading = ref(false)
  const errorMsg = ref('')

  /**
   * 拉取当前页。loader 接收已解析的页码/每页条数，返回分页信封；附加请求（如分类实体）
   * 与副作用都在 loader 内完成。
   *
   * `onLoaded` 只在「本次响应仍是最新一次」时调用 —— 附加请求的结果（需要和列表保持
   * 同一版本）应放这里应用，否则乱序响应会把旧请求的实体盖到新列表上。
   */
  async function load(
    loader: (page: number, pageSize: number) => Promise<PaginatedResponse<Article>>,
    onLoaded?: () => void,
  ) {
    const seq = guard.begin()
    loading.value = true
    errorMsg.value = ''
    try {
      const data = await loader(page.value, pageSize.value)
      if (!guard.isLatest(seq)) return
      articles.value = data.items
      total.value = data.total
      onLoaded?.()
      clampPage(data.total, pageSize.value)
    } catch (e) {
      if (!guard.isLatest(seq)) return
      errorMsg.value = errorMessage(e, options.fallbackMessage ?? '加载失败')
    } finally {
      if (guard.isLatest(seq)) loading.value = false
    }
  }

  return { page, pageSize, articles, total, loading, errorMsg, load }
}