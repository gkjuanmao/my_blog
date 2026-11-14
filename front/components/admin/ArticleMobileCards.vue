<script setup lang="ts">
/**
 * 后台文章列表的移动端视图（≤820px 替代表格）。
 * 与桌面表格共用页面的 `selectedIds`（受控），只上报交互。
 */
import type { Article } from '~/types/api'

defineProps<{
  articles: Article[]
  loading: boolean
  selectedIds: number[]
}>()

const emit = defineEmits<{
  toggleSelect: [id: number]
  edit: [id: number]
  delete: [row: Article]
}>()
</script>

<template>
  <div class="ad-mcards" :class="{ 'ad-loading': loading }">
    <div
      v-for="row in articles"
      :key="row.id"
      class="ad-mcard"
      :class="{ 'is-selected': selectedIds.includes(row.id) }"
    >
      <input
        type="checkbox"
        class="ad-check"
        :checked="selectedIds.includes(row.id)"
        :aria-label="`选择《${row.title}》`"
        @change="emit('toggleSelect', row.id)"
      >
      <img v-if="row.cover_image_url" :src="row.cover_image_url" alt="">
      <span v-else aria-hidden="true" />
      <div>
        <p class="ad-mcard__title">{{ row.title }}</p>
        <p class="ad-mcard__meta">
          {{ row.category?.name ?? '未分类' }} · {{ formatDateCompact(row.publish_time) }}
          · {{ row.is_published ? `${row.views} 次阅读` : '草稿' }}
        </p>
        <div class="ad-mcard__acts">
          <button class="ad-link" type="button" @click="emit('edit', row.id)">
            {{ row.is_published ? '编辑' : '继续编辑' }}
          </button>
          <button class="ad-link ad-link--danger" type="button" @click="emit('delete', row)">
            删除
          </button>
        </div>
      </div>
    </div>
    <p v-if="!loading && !articles.length" class="ad-mcards__empty">
      没有符合条件的稿件 —— 换个筛选条件，或者直接写一篇。
    </p>
  </div>
</template>
