<script setup lang="ts">
/**
 * 后台分页：等宽页码 + 墨青当前页，落在页脚里（页脚恒在窗口底部）。
 *
 * 与 `AppPagination`（Element Plus，公开页共用）分开：公开页的皮肤不能改，
 * 后台需要「第 N / M 页 · 共 K 篇」这种台账式脚注。
 */
const props = withDefaults(
  defineProps<{
    total: number
    pageSizes?: number[]
    /** 每页篇数是否可切换 */
    sizeSelectable?: boolean
    /** 计数单位：文章是「篇」，账号是「个」 */
    unit?: string
  }>(),
  { pageSizes: () => [10, 20, 50], sizeSelectable: true, unit: '篇' },
)

const page = defineModel<number>('page', { required: true })
const pageSize = defineModel<number>('pageSize', { required: true })

const lastPage = computed(() => Math.max(1, Math.ceil(props.total / Math.max(1, pageSize.value))))

/** 首尾 + 当前页两侧，其余折叠为省略号 */
const items = computed<Array<number | 'gap'>>(() => {
  const last = lastPage.value
  if (last <= 7) return Array.from({ length: last }, (_, i) => i + 1)
  const set = new Set<number>([1, last, page.value, page.value - 1, page.value + 1])
  const list = [...set].filter(n => n >= 1 && n <= last).sort((a, b) => a - b)
  const out: Array<number | 'gap'> = []
  list.forEach((n, i) => {
    if (i > 0 && n - (list[i - 1] as number) > 1) out.push('gap')
    out.push(n)
  })
  return out
})

function go(next: number) {
  const target = Math.min(Math.max(1, next), lastPage.value)
  if (target !== page.value) page.value = target
}

function onSizeChange(event: Event) {
  const value = Number((event.target as HTMLSelectElement).value)
  if (!Number.isFinite(value) || value === pageSize.value) return
  pageSize.value = value
  page.value = 1
}
</script>

<template>
  <div class="ad-footbar">
    <div class="ad-pager">
      <p class="ad-pager__meta">
        第 <b>{{ page }}</b> / {{ lastPage }} 页
        <span aria-hidden="true">·</span> 共 {{ total }} {{ unit }}
        <template v-if="sizeSelectable">
          <span aria-hidden="true">·</span>
          <label>
            <span class="ad-sr">每页条数</span>
            <select class="ad-pager__size" :value="pageSize" @change="onSizeChange">
              <option v-for="size in pageSizes" :key="size" :value="size">每页 {{ size }} {{ unit }}</option>
            </select>
          </label>
        </template>
        <template v-else>
          <span aria-hidden="true">·</span> 每页 {{ pageSize }} {{ unit }}
        </template>
      </p>

      <slot name="extra" />

      <nav class="ad-pager__nav" aria-label="分页">
        <button class="ad-pager__step" type="button" :disabled="page <= 1" @click="go(page - 1)">
          上一页
        </button>
        <template v-for="(item, index) in items" :key="`${item}-${index}`">
          <span v-if="item === 'gap'" class="ad-pager__gap" aria-hidden="true">…</span>
          <button
            v-else
            class="ad-pager__num"
            type="button"
            :aria-current="item === page ? 'page' : undefined"
            @click="go(item)"
          >
            {{ item }}
          </button>
        </template>
        <button
          class="ad-pager__step"
          type="button"
          :disabled="page >= lastPage"
          @click="go(page + 1)"
        >
          下一页
        </button>
      </nav>
    </div>
  </div>
</template>
