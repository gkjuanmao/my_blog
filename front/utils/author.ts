/**
 * 作者筛选的纯函数（无 Nuxt 依赖，便于单测）。
 *
 * 为什么单独抽出来：URL query 是 string | string[] | undefined 的联合类型，
 * 「解析成 id」与「回写成 query」这两步在任何页面里都容易写成
 * `Number(route.query.author)` 这种会把数组解析成 NaN 的写法。
 */

/** 从 URL query 里解析作者 id；非法（缺省 / 数组 / 非数字 / <1）一律 null */
export function parseAuthorId(raw: unknown): number | null {
  const value = Array.isArray(raw) ? raw[0] : raw
  if (typeof value !== 'string' || value.trim() === '') return null
  const n = Number(value)
  return Number.isInteger(n) && n >= 1 ? n : null
}

/** 作者筛选真正会写进 URL 的值；null 表示「全部」= 不写这个键 */
export function authorQueryValue(authorId: number | null): string | undefined {
  return authorId === null ? undefined : String(authorId)
}

/**
 * 生成「切换作者」后的 query。
 *
 * 两个必须做到的点：
 * 1. 作者为空时**删掉** author 键（URL 干净，且「全部」不产生额外缓存分叉）；
 * 2. 切换作者必须**重置 page**——否则在第 5 页切到只有 1 篇文章的作者会看到空页。
 *
 * 返回类型故意是「任意 query 记录」而不是 Vue Router 的 `LocationQueryRaw`：
 * 本函数是纯函数、要被 vitest 直接调用；类型适配放在 composable 里做。
 */
export function buildAuthorQuery(
  query: Record<string, unknown>,
  authorId: number | null,
): Record<string, unknown> {
  const next: Record<string, unknown> = { ...query }
  const value = authorQueryValue(authorId)
  if (value === undefined) delete next.author
  else next.author = value
  delete next.page
  return next
}
