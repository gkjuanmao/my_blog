/**
 * 作者筛选的 URL 状态（`?author=<id>`）。
 *
 * 与 `usePageQuery` 的分工：那个只管 page/page_size，这个只管作者；
 * 两者都写 `router.replace` 且都保留对方的键，所以可以同时使用。
 * 共用理由：URL 是唯一真相——刷新、后退、分享链接都能回到「某人的文章第 2 页」。
 */
import type { LocationQueryRaw } from 'vue-router'

import { buildAuthorQuery, parseAuthorId } from '~/utils/author'

export function useAuthorQuery() {
  const route = useRoute()
  const router = useRouter()

  const authorId = computed(() => parseAuthorId(route.query.author))

  function selectAuthor(next: number | null) {
    if (next === authorId.value) return
    const query = buildAuthorQuery(
      route.query as Record<string, unknown>,
      next,
    ) as LocationQueryRaw
    router.replace({ query })
  }

  return { authorId, selectAuthor }
}
