/**
 * 竞态守卫：快速翻页/切换筛选时，旧请求可能后到并覆盖新数据。
 *
 * 用法（每次发起请求前 begin()，回来后 isLatest() 判定是否仍是最新一次）：
 *   const guard = useRequestGuard()
 *   const seq = guard.begin()
 *   const data = await fetchSomething()
 *   if (!guard.isLatest(seq)) return   // 已有更新的请求，丢弃本次结果
 *
 * 相比 AbortController，序号法无需额外处理 AbortError，且对不支持取消的调用同样有效。
 */
export function useRequestGuard() {
  let current = 0

  function begin(): number {
    current += 1
    return current
  }

  function isLatest(sequence: number): boolean {
    return sequence === current
  }

  return { begin, isLatest }
}