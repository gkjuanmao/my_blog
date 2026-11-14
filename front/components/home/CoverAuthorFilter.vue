<script setup lang="ts">
/**
 * 首页作者筛选器（chips）。
 *
 * 为什么是 chips 而不是下拉：个人博客的作者是个位数，一屏能放下时 chips 比下拉少一次点击，
 * 也把「这里可以按人筛选」直接摆在明面上；作者数超过阈值（默认 8）时折叠成「更多」，
 * 避免把区块标题挤走。
 *
 * 无障碍：容器 `role="group"` + 每个 chip `aria-pressed`，与后台 `.ad-segs` 同一套语义；
 * 当前项同时用视觉（实底）和 `aria-pressed` 表达，不靠颜色单独承载信息。
 */
import type { Author } from '~/types/api'

const props = withDefaults(
  defineProps<{
    authors: Author[]
    /** 当前选中的作者 id；null = 全部 */
    current: number | null
    /** 超过这个数量折叠成「更多」 */
    maxVisible?: number
  }>(),
  { maxVisible: 8 },
)

const emit = defineEmits<{ select: [id: number | null] }>()

const expanded = ref(false)

/** 只有一个作者时整块不渲染：那时「全部」和「某人」是同一批文章，纯噪音 */
const visible = computed(() => props.authors.length > 1)

const shown = computed(() =>
  expanded.value ? props.authors : props.authors.slice(0, props.maxVisible),
)
const hiddenCount = computed(() => Math.max(0, props.authors.length - props.maxVisible))

function label(author: Author): string {
  return `${author.username} ${author.article_count}`
}
</script>

<template>
  <div v-if="visible" class="cv-author" role="group" aria-label="按作者筛选">
    <button
      type="button"
      class="cv-author__chip"
      :aria-pressed="current === null"
      @click="emit('select', null)"
    >
      全部作者
    </button>
    <button
      v-for="author in shown"
      :key="author.id"
      type="button"
      class="cv-author__chip"
      :aria-pressed="current === author.id"
      @click="emit('select', author.id)"
    >
      {{ label(author) }}
    </button>
    <button
      v-if="hiddenCount && !expanded"
      type="button"
      class="cv-author__chip cv-author__chip--more"
      :aria-expanded="false"
      @click="expanded = true"
    >
      更多 {{ hiddenCount }} 位
    </button>
  </div>
</template>
