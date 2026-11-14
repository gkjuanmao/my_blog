<script setup lang="ts">
/**
 * 后台文章列表的桌面视图：原生 <table> 的「台账」样式（细线 + 书法体标题 + 等宽数字）。
 *
 * 勾选状态仍由页面持有（`selectedIds`），表格只做展示与事件上报；
 * 排序只支持「发布时间」，点表头切换（服务端排序，见页面的 sortOrder）。
 */
import type { Article } from '~/types/api'

const props = defineProps<{
  articles: Article[]
  loading: boolean
  /** 当前勾选的文章 id（页面持有） */
  selectedIds: number[]
  /** 当前发布时间排序方向（用于表头箭头） */
  order: 'asc' | 'desc'
}>()

const emit = defineEmits<{
  sortChange: [payload: { prop: string | null; order: string | null }]
  toggleSelect: [id: number]
  toggleSelectAll: []
  edit: [id: number]
  delete: [row: Article]
}>()

const allSelected = computed(
  () => props.articles.length > 0 && props.selectedIds.length === props.articles.length,
)
const someSelected = computed(() => props.selectedIds.length > 0 && !allSelected.value)

function toggleSort() {
  emit('sortChange', {
    prop: 'publish_time',
    order: props.order === 'desc' ? 'ascending' : 'descending',
  })
}
</script>

<template>
  <div class="ad-tablewrap" :class="{ 'ad-loading': loading }" :aria-busy="loading ? 'true' : 'false'">
    <table class="ad-table">
      <caption class="ad-sr">
        文章列表，共 {{ articles.length }} 篇，按发布时间{{ order === 'desc' ? '倒序' : '正序' }}
      </caption>
      <thead>
        <tr>
          <th class="ad-table__check">
            <el-checkbox
              :model-value="allSelected"
              :indeterminate="someSelected"
              aria-label="全选本页"
              @change="emit('toggleSelectAll')"
            />
          </th>
          <th class="ad-table__thumb"><span class="ad-sr">封面</span></th>
          <th>标题</th>
          <th class="ad-table__cat">栏目</th>
          <th class="ad-table__state">状态</th>
          <th class="ad-table__pub">
            <button
              class="ad-sort"
              type="button"
              :title="order === 'desc' ? '改为最早在前' : '改为最新在前'"
              @click="toggleSort"
            >
              发布时间 <i aria-hidden="true">{{ order === 'desc' ? '↓' : '↑' }}</i>
            </button>
          </th>
          <th class="num ad-table__views">阅读</th>
          <th class="ad-table__acts">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in articles"
          :key="row.id"
          :class="{ 'is-selected': selectedIds.includes(row.id) }"
        >
          <td class="ad-table__check">
            <el-checkbox
              :model-value="selectedIds.includes(row.id)"
              :aria-label="`选择《${row.title}》`"
              @change="emit('toggleSelect', row.id)"
            />
          </td>
          <td class="ad-table__thumb">
            <img v-if="row.cover_image_url" :src="row.cover_image_url" alt="">
            <span v-else class="blank" aria-hidden="true" />
          </td>
          <td class="ad-table__title">
            <!-- title 属性：标题被省略号截断时，悬停即可读到完整文本（不额外造 tooltip 组件） -->
            <NuxtLink :to="`/administrator/articles/edit/${row.id}`" :title="row.title">
              {{ row.title }}
            </NuxtLink>
            <span class="ad-table__slug" :title="`${row.slug} · ${row.author_name}`">
              {{ row.slug }} · {{ row.author_name }}
            </span>
          </td>
          <td class="ad-table__cat">
            <span v-if="row.category" class="ad-chip">{{ row.category.name }}</span>
            <span v-else class="ad-table__views">—</span>
          </td>
          <td>
            <span class="ad-status" :class="{ 'ad-status--draft': !row.is_published }">
              <i aria-hidden="true" />{{ row.is_published ? '已发布' : '草稿' }}
            </span>
          </td>
          <td class="ad-table__date">{{ formatDateCompact(row.publish_time) }}</td>
          <td class="ad-table__views num">{{ row.is_published ? row.views : '—' }}</td>
          <td class="ad-table__acts">
            <button class="ad-link" type="button" @click="emit('edit', row.id)">
              {{ row.is_published ? '编辑' : '继续编辑' }}
            </button>
            <button class="ad-link ad-link--danger" type="button" @click="emit('delete', row)">
              删除
            </button>
          </td>
        </tr>
        <tr v-if="!articles.length">
          <td colspan="8">
            <p class="ad-rows-empty">
              {{ loading ? '正在加载…' : '没有符合条件的稿件 —— 换个筛选条件，或者直接写一篇。' }}
            </p>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
