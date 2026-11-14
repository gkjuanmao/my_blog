<script setup lang="ts">
/**
 * 分类（栏目）台账：左侧带印章的索引列 + 右侧常驻设置面板。
 *
 * 数据层仍由 `useCrudTable` 负责（列表 / 新增 / 更新 / 删除），
 * 本组件只管面板状态与表单校验。索引列里点线引线把栏目与稿件数连起来（见 CSS）。
 */
import type { CrudRow } from '~/composables/useCrudTable'

const props = defineProps<{
  list: CrudRow[]
  loading: boolean
  /** 每个栏目下的稿件数（页面用文章列表统计） */
  counts: Record<number, number>
  submit: (payload: Record<string, string>, editing: CrudRow | null) => Promise<void>
  remove: (row: CrudRow) => Promise<void>
}>()

const emit = defineEmits<{ changed: [] }>()

const DEFAULT_SLUG = 'default-category'

const editing = ref<CrudRow | null>(null)
const saving = ref(false)
const nameError = ref('')
const form = reactive({ name: '', slug: '', description: '' })

const panelTitle = computed(() => (editing.value ? editing.value.name : '新建栏目'))
const panelEyebrow = computed(() => (editing.value ? '编辑栏目' : '栏目设置'))
const panelHint = computed(() =>
  editing.value ? `${editing.value.slug} · ${props.counts[editing.value.id] ?? 0} 篇稿件` : '留空 slug 时按名称生成拼音',
)
const emptyCount = computed(() => props.list.filter(row => (props.counts[row.id] ?? 0) === 0).length)

function resetForm() {
  editing.value = null
  form.name = ''
  form.slug = ''
  form.description = ''
  nameError.value = ''
}

function openEdit(row: CrudRow) {
  editing.value = row
  form.name = row.name
  form.slug = row.slug
  form.description = row.description ?? ''
  nameError.value = ''
}

async function handleSave() {
  if (!form.name.trim()) {
    nameError.value = '请填写栏目名称'
    return
  }
  nameError.value = ''
  saving.value = true
  try {
    await props.submit(
      {
        name: form.name.trim(),
        slug: form.slug.trim(),
        description: form.description.trim(),
      },
      editing.value,
    )
    ElMessage.success(editing.value ? '栏目已更新' : '栏目已创建')
    resetForm()
    emit('changed')
  } catch (e) {
    ElMessage.error(errorMessage(e, '保存失败'))
  } finally {
    saving.value = false
  }
}

async function handleDelete(row: CrudRow) {
  try {
    await ElMessageBox.confirm(
      `删除「${row.name}」后，栏目下的文章会回到「默认分类」，文章本身不会丢失。`,
      '删除栏目',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await props.remove(row)
    ElMessage.success('栏目已删除')
    if (editing.value?.id === row.id) resetForm()
    emit('changed')
  } catch (e) {
    ElMessage.error(errorMessage(e, '删除失败'))
  }
}
</script>

<template>
  <div class="ad-split ad-split--wide">
    <div class="ad-split__col ad-split__col--flush">
      <p v-if="loading" class="ad-block__note" style="padding: 20px 0">正在加载栏目…</p>
      <p v-else-if="!list.length" class="ad-block__note" style="padding: 20px 0">
        还没有栏目 —— 在右侧新建第一个，稿件才有地方归档。
      </p>
      <template v-else>
        <div v-for="row in list" :key="row.id" class="ad-catitem">
          <span class="ad-seal" aria-hidden="true">{{ row.name.charAt(0) }}</span>
          <div class="ad-catitem__body">
            <p class="ad-catitem__name">
              {{ row.name }}
              <span v-if="row.slug === DEFAULT_SLUG" class="ad-chip ad-chip--sys">系统</span>
            </p>
            <p class="ad-catitem__slug">{{ row.slug }}</p>
            <p class="ad-catitem__desc">{{ row.description || '暂无描述' }}</p>
          </div>
          <p class="ad-catitem__count">
            {{ counts[row.id] ?? 0 }}<small>篇</small>
          </p>
          <div class="ad-catitem__acts">
            <button class="ad-link" type="button" @click="openEdit(row)">编辑</button>
            <button
              v-if="row.slug !== DEFAULT_SLUG"
              class="ad-link ad-link--danger"
              type="button"
              @click="handleDelete(row)"
            >
              删除
            </button>
            <span v-else class="ad-hint">不可删除</span>
          </div>
        </div>
        <p class="ad-block__note">
          {{ emptyCount ? `${emptyCount} 个栏目还没有稿件。` : '每个栏目都有稿件了。' }}
        </p>
      </template>
    </div>

    <aside class="ad-split__aside ad-split__aside--flush">
      <p class="ad-panel__eyebrow">{{ panelEyebrow }}</p>
      <h2 class="ad-panel__title">{{ panelTitle }}</h2>
      <p class="ad-panel__hint">{{ panelHint }}</p>

      <form class="ad-form" @submit.prevent="handleSave">
        <label class="ad-field">
          <span>名称</span>
          <input v-model="form.name" type="text" placeholder="如：国内游" @input="nameError = ''">
          <span v-if="nameError" class="ad-error">{{ nameError }}</span>
        </label>
        <label class="ad-field">
          <span>Slug</span>
          <input v-model="form.slug" type="text" placeholder="留空自动生成拼音，如 guo-nei-you">
        </label>
        <label class="ad-field">
          <span>描述</span>
          <input v-model="form.description" type="text" placeholder="一句话说明这个栏目写什么">
        </label>
        <div class="ad-form__acts">
          <button class="ad-btn ad-btn--primary" type="submit" :disabled="saving">
            {{ saving ? '保存中…' : '保存栏目' }}
          </button>
          <button v-if="editing" class="ad-btn ad-btn--ghost" type="button" @click="resetForm">
            取消编辑
          </button>
        </div>
      </form>

      <div v-if="editing && editing.slug !== DEFAULT_SLUG" class="ad-panel__danger">
        <p>
          删除后，这个栏目下的 {{ counts[editing.id] ?? 0 }} 篇文章会回到「默认分类」，
          文章本身不会丢失。
        </p>
        <div class="ad-form__acts" style="margin-top: 10px">
          <button class="ad-btn ad-btn--danger ad-btn--sm" type="button" @click="handleDelete(editing)">
            删除栏目
          </button>
        </div>
      </div>

      <p class="ad-panel__note">
        删除栏目不会删除文章；栏目下的文章会回到「默认分类」。<br>
        Slug 用于前台地址，留空时按名称生成拼音；改动会影响前台链接，慎改。
      </p>
    </aside>
  </div>
</template>
