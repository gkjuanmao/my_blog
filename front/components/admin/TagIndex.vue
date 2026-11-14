<script setup lang="ts">
/**
 * 标签台账：1px 缝的索引卡网格（名称 + slug + 使用数）+ 右侧编辑面板。
 * 数据层仍由 `useCrudTable` 负责；筛选与排序在页面里做（工具带在页面级）。
 */
import type { CrudRow } from '~/composables/useCrudTable'

const props = defineProps<{
  list: CrudRow[]
  loading: boolean
  /** 每条形如挂在多少篇文章上（页面用文章列表统计） */
  counts: Record<number, number>
  submit: (payload: Record<string, string>, editing: CrudRow | null) => Promise<void>
  remove: (row: CrudRow) => Promise<void>
}>()

const emit = defineEmits<{ changed: [] }>()

const DEFAULT_SLUG = 'default-tag'

const selected = ref<CrudRow | null>(null)
const creating = ref(false)
const saving = ref(false)
const nameError = ref('')
const form = reactive({ name: '', slug: '' })

const panelTitle = computed(() => {
  if (creating.value) return '新建标签'
  return selected.value?.name ?? '新标签'
})
const panelHint = computed(() => {
  if (creating.value) return '留空 slug 时按名称生成拼音'
  if (!selected.value) return '先在左侧点一格'
  return `${selected.value.slug} · 挂在 ${props.counts[selected.value.id] ?? 0} 篇文章上`
})

/** 列表加载完成后默认选中第一条，面板不至于空着 */
watch(
  () => props.list,
  (list) => {
    if (selected.value && list.some(row => row.id === selected.value?.id)) return
    if (!creating.value) selected.value = list[0] ?? null
  },
  { immediate: true },
)

function openEdit(row: CrudRow) {
  creating.value = false
  selected.value = row
  form.name = row.name
  form.slug = row.slug
  nameError.value = ''
}

function startCreate() {
  creating.value = true
  selected.value = null
  form.name = ''
  form.slug = ''
  nameError.value = ''
}

watch(
  () => selected.value,
  (row) => {
    if (!row) return
    form.name = row.name
    form.slug = row.slug
  },
  { immediate: true },
)

async function handleSave() {
  if (!form.name.trim()) {
    nameError.value = '请填写标签名称'
    return
  }
  nameError.value = ''
  saving.value = true
  try {
    await props.submit(
      { name: form.name.trim(), slug: form.slug.trim() },
      creating.value ? null : selected.value,
    )
    ElMessage.success(creating.value ? '标签已创建' : '标签已更新')
    emit('changed')
    if (creating.value) {
      creating.value = false
    }
  } catch (e) {
    ElMessage.error(errorMessage(e, '保存失败'))
  } finally {
    saving.value = false
  }
}

defineExpose({ startCreate })

async function handleDelete() {
  const row = selected.value
  if (!row) return
  try {
    await ElMessageBox.confirm(
      `「${row.name}」将从所有文章上解除关联，文章本身不受影响。`,
      '删除标签',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await props.remove(row)
    ElMessage.success('标签已删除')
    emit('changed')
  } catch (e) {
    ElMessage.error(errorMessage(e, '删除失败'))
  }
}

/* 索引卡铺满整栏：按当前列数补齐末行空格子，否则末尾会露出一条灰绿空带 */
const gridRef = ref<HTMLElement | null>(null)
const fillers = ref(0)
let observer: ResizeObserver | null = null

function measure() {
  const el = gridRef.value
  if (!el) return
  const columns = getComputedStyle(el).gridTemplateColumns.split(' ').filter(Boolean).length
  const cells = props.list.length + 1 // + 「新建标签」那一格
  fillers.value = columns > 1 ? (columns - (cells % columns)) % columns : 0
}

onMounted(() => {
  measure()
  if (gridRef.value && typeof ResizeObserver !== 'undefined') {
    observer = new ResizeObserver(measure)
    observer.observe(gridRef.value)
  }
})

onBeforeUnmount(() => {
  observer?.disconnect()
})

watch(
  () => props.list.length,
  () => nextTick(measure),
)
</script>

<template>
  <div class="ad-split ad-split--wide">
    <div
      class="ad-split__col ad-split__col--flush"
      style="display: flex; flex-direction: column; min-height: 0"
    >
      <p v-if="loading" class="ad-block__note" style="padding: 20px 0">正在加载标签…</p>
      <p v-else-if="!list.length" class="ad-block__note" style="padding: 20px 0">
        还没有标签 —— 点「新建标签」，给文章一个可检索的入口。
      </p>
      <div v-else ref="gridRef" class="ad-taggrid">
        <button
          v-for="row in list"
          :key="row.id"
          class="ad-tagcell"
          type="button"
          :aria-pressed="!creating && selected?.id === row.id"
          @click="openEdit(row)"
        >
          <span class="ad-tagcell__hash" aria-hidden="true">#</span>
          <span class="ad-tagcell__body">
            <span class="ad-tagcell__name">{{ row.name }}</span>
            <span class="ad-tagcell__slug">{{ row.slug }}</span>
          </span>
          <span class="ad-tagcell__num">{{ counts[row.id] ?? 0 }}</span>
        </button>

        <button class="ad-tagcell ad-tagcell--new" type="button" @click="startCreate">
          <AdminIcon name="plus" :size="13" />新建标签
        </button>

        <div v-for="n in fillers" :key="`void-${n}`" class="ad-tagcell ad-tagcell--void" />
      </div>
    </div>

    <aside class="ad-split__aside ad-split__aside--flush">
      <p class="ad-panel__eyebrow">标签设置</p>
      <h2 class="ad-panel__title">{{ panelTitle }}</h2>
      <p class="ad-panel__hint">{{ panelHint }}</p>

      <form class="ad-form" @submit.prevent="handleSave">
        <label class="ad-field">
          <span>名称</span>
          <input v-model="form.name" type="text" placeholder="如：自驾" @input="nameError = ''">
          <span v-if="nameError" class="ad-error">{{ nameError }}</span>
        </label>
        <label class="ad-field">
          <span>Slug</span>
          <input v-model="form.slug" type="text" placeholder="留空自动生成拼音">
        </label>
        <div class="ad-form__acts">
          <button class="ad-btn ad-btn--primary" type="submit" :disabled="saving">
            {{ saving ? '保存中…' : '保存标签' }}
          </button>
          <button v-if="creating" class="ad-btn ad-btn--ghost" type="button" @click="creating = false">
            取消
          </button>
        </div>
      </form>

      <div v-if="!creating && selected" class="ad-panel__danger">
        <p v-if="selected.slug !== DEFAULT_SLUG">
          删除只解除它和 {{ counts[selected.id] ?? 0 }} 篇文章的关联，文章本身不受影响。
        </p>
        <p v-else>「默认标签」是系统标签，受保护，不可删除。</p>
        <div v-if="selected.slug !== DEFAULT_SLUG" class="ad-form__acts" style="margin-top: 10px">
          <button class="ad-btn ad-btn--danger ad-btn--sm" type="button" @click="handleDelete">
            删除此标签
          </button>
        </div>
      </div>

      <p class="ad-panel__note">
        标签宜少不宜多：超过 30 条就开始互相重叠，前台标签页也会变成长列表。
      </p>
    </aside>
  </div>
</template>
