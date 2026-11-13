<script setup lang="ts">
/**
 * 标签台账：索引卡网格（名称 + slug 直接可读）+ 右侧编辑面板。
 * 数据层仍由 `useCrudTable` 负责。
 */
import type { CrudRow } from '~/composables/useCrudTable'

const props = defineProps<{
  list: CrudRow[]
  loading: boolean
  submit: (payload: Record<string, string>, editing: CrudRow | null) => Promise<void>
  remove: (row: CrudRow) => Promise<void>
}>()

const emit = defineEmits<{ changed: [] }>()

const DEFAULT_SLUG = 'default-tag'

const selected = ref<CrudRow | null>(null)
const creating = ref(false)
const saving = ref(false)
const nameError = ref('')
const query = ref('')
const form = reactive({ name: '', slug: '' })

const filtered = computed(() => {
  const word = query.value.trim().toLowerCase()
  if (!word) return props.list
  return props.list.filter(
    row =>
      row.name.toLowerCase().includes(word) || row.slug.toLowerCase().includes(word),
  )
})

const panelTitle = computed(() => {
  if (creating.value) return '新建标签'
  return selected.value?.name ?? '新标签'
})
const panelEyebrow = computed(() => (creating.value ? '标签设置' : '标签设置'))

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
</script>

<template>
  <div>
    <div class="ad-toolbar" style="margin-bottom: 22px">
      <label class="ad-field" style="max-width: 300px; flex: 1">
        <span>搜索标签</span>
        <input v-model="query" type="search" placeholder="输入名称或 slug…" autocomplete="off">
      </label>
      <span class="ad-toolbar__spacer" />
    </div>

    <div class="ad-columns" style="margin-top: 0">
      <section class="ad-block" aria-labelledby="ad-tagall-title">
        <div class="ad-block__head">
          <h2 id="ad-tagall-title">全部标签</h2>
          <span class="ad-block__count">{{ list.length }} 条</span>
          <span class="ad-block__count" style="margin-left: auto">选中一条，右侧编辑</span>
        </div>

        <div v-if="loading" class="ad-loading" style="padding: 40px 0; color: var(--hp-ink-3)">
          正在加载标签…
        </div>
        <template v-else-if="filtered.length">
          <ul class="ad-tagcards">
            <li v-for="row in filtered" :key="row.id">
              <button
                class="ad-tagcard"
                type="button"
                :aria-pressed="!creating && selected?.id === row.id"
                @click="openEdit(row)"
              >
                <span class="ad-tagcard__name">{{ row.name }}</span>
                <span class="ad-tagcard__slug">{{ row.slug }}</span>
              </button>
            </li>
          </ul>
        </template>
        <p v-else class="ad-block__note">
          {{ query ? '没有匹配的标签 —— 清空搜索，或者新建一条。' : '还没有标签 —— 在右侧新建第一条。' }}
        </p>
      </section>

      <aside class="ad-panel" aria-labelledby="ad-tag-panel-title">
        <div class="ad-panel__head">
          <p class="ad-panel__eyebrow">{{ panelEyebrow }}</p>
          <h2 id="ad-tag-panel-title" class="ad-panel__title">{{ panelTitle }}</h2>
        </div>

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
          </div>
        </form>

        <div v-if="!creating && selected" class="ad-panel__danger">
          <button
            v-if="selected.slug !== DEFAULT_SLUG"
            class="ad-link ad-link--danger"
            type="button"
            @click="handleDelete"
          >
            删除此标签
          </button>
          <span v-else class="ad-hint">「默认标签」受保护，不可删除。</span>
          <p class="ad-form__note" style="border: 0; padding-top: 8px; margin-top: 0">
            删除标签只解除它与文章的关联，文章本身不受影响。
          </p>
        </div>
      </aside>
    </div>
  </div>
</template>
