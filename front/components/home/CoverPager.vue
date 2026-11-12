<script setup lang="ts">
/**
 * 首页分页行。
 *
 * 为什么不复用 `AppPagination`（02-ux-spec.md N6）：
 *  ① 它在 ≤639px 传 `:small="true"`，按钮塌成 24px（触控不合格）；
 *  ② 它 ≥640px 会多渲染一个 `sizes` 下拉，与首页的三段按钮重复；
 *  ③ 它的断点是 639，首页是 768，错档。
 * 所以这里自绘，断点与首页一致，并保证：首末页永远可达、当前页永远可见、圆点只出现在当前页。
 *
 * 分页计算（对任意 page_size 成立）：
 *  - `lastPage = ceil(total / pageSize)`，最小 1；
 *  - 页数 ≤ 7 时全量显示，不做省略；
 *  - 否则固定「首 + 尾 + 当前 ±1」，中间断档处插省略号 —— 因此首末页永远有按钮，
 *    无论 total 多大都不会出现「回不到第 1 页」。
 */
const props = defineProps<{
  page: number
  pageSize: number
  total: number
  /** 翻页请求进行中：分页行保持可见但不可点（不要整块消失，否则高度跳动） */
  loading?: boolean
}>()

const emit = defineEmits<{
  'update:page': [page: number]
  'update:pageSize': [pageSize: number]
}>()

const SIZE_OPTIONS = [10, 20, 50] as const
const SIBLINGS = 1
/** 首 + 尾 + 当前 + 两侧 + 两个省略号 */
const MAX_SLOTS = SIBLINGS * 2 + 5

const lastPage = computed(() => Math.max(1, Math.ceil(props.total / Math.max(1, props.pageSize))))

function range(start: number, end: number): number[] {
  const out: number[] = []
  for (let n = start; n <= end; n += 1) out.push(n)
  return out
}

/** 页码段（数字 + 省略号占位） */
const pages = computed<(number | 'gap')[]>(() => {
  const last = lastPage.value
  const current = Math.min(Math.max(props.page, 1), last)
  if (last <= MAX_SLOTS) return range(1, last)

  const left = Math.max(2, current - SIBLINGS)
  const right = Math.min(last - 1, current + SIBLINGS)
  const items: (number | 'gap')[] = [1]
  if (left > 2) items.push('gap')
  items.push(...range(left, right))
  if (right < last - 1) items.push('gap')
  items.push(last)
  return items
})

/** 读屏播报（N7：页码点击后内容原地替换，必须给出提示） */
const announce = computed(
  () => `已切换到第 ${props.page} 页，共 ${lastPage.value} 页，每页 ${props.pageSize} 篇`,
)

function go(target: number) {
  if (!Number.isInteger(target)) return
  if (target < 1 || target > lastPage.value || target === props.page) return
  emit('update:page', target)
}

function changeSize(size: number) {
  if (size === props.pageSize) return
  // usePageQuery 的 pageSize setter 会把 page 一并重置到 1，这里不重复写 page
  emit('update:pageSize', size)
}
</script>

<template>
  <nav
    class="cv-pager-row"
    aria-label="分页导航"
    :data-busy="loading ? 'true' : 'false'"
  >
    <div class="cv-size-group" role="group" aria-label="每页条数">
      <span class="cv-size-label" aria-hidden="true">每页</span>
      <button
        v-for="size in SIZE_OPTIONS"
        :key="size"
        type="button"
        class="cv-size-btn"
        :aria-pressed="pageSize === size"
        @click="changeSize(size)"
      >
        {{ size }}
      </button>
    </div>

    <div class="cv-pager">
      <button
        type="button"
        class="cv-pager__step"
        :disabled="page <= 1"
        @click="go(page - 1)"
      >
        ← 上一页
      </button>

      <template v-for="(item, i) in pages" :key="`${item}-${i}`">
        <span v-if="item === 'gap'" class="cv-pager__gap" aria-hidden="true">…</span>
        <button
          v-else
          type="button"
          class="cv-pager__num"
          :aria-label="`第 ${item} 页`"
          :aria-current="item === page ? 'page' : undefined"
          @click="go(item)"
        >
          {{ item }}
        </button>
      </template>

      <button
        type="button"
        class="cv-pager__step"
        :disabled="page >= lastPage"
        @click="go(page + 1)"
      >
        下一页 →
      </button>
    </div>

    <p class="sr-only" role="status" aria-live="polite">{{ announce }}</p>
  </nav>
</template>
