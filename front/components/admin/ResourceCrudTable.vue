<script setup lang="ts">
/**
 * 「简单资源」列表 + 新建/编辑弹窗的通用视图（FE-10）。
 *
 * 桌面 el-table / 移动卡片 / 弹窗表单全部由 `columns` + `fields` 声明驱动，
 * 分类与标签页因此可以共用同一份模板（此前是两份 1:1 复制的实现）。
 * 本地状态（弹窗、正在编辑的行、表单值、保存中、删除确认）都由本组件持有；
 * 数据请求通过 `submit` / `remove` 两个函数 prop 委托给 `useCrudTable`。
 */
import type { FormRules } from 'element-plus'
import type { CrudColumn, CrudField, CrudRow } from '~/composables/useCrudTable'

const props = defineProps<{
  /** 页面标题，如「分类管理」 */
  title: string
  /** 实体中文名，如「分类」 */
  label: string
  list: CrudRow[]
  loading: boolean
  columns: CrudColumn[]
  fields: CrudField[]
  /** 新增或更新（editing 为 null 表示新增） */
  submit: (payload: Record<string, string>, editing: CrudRow | null) => Promise<void>
  /** 删除（确认弹窗由本组件负责） */
  remove: (row: CrudRow) => Promise<void>
  /** 移动端卡片是否展示描述（分类有、标签没有） */
  showDescription?: boolean
  /** 移动端卡片名称前缀（标签用「# 」） */
  namePrefix?: string
}>()

const emit = defineEmits<{ changed: [] }>()

const dialogVisible = ref(false)
const editing = ref<CrudRow | null>(null)
const saving = ref(false)
const form = reactive<Record<string, string>>(
  Object.fromEntries(props.fields.map(field => [field.key, ''])),
)
// 仅第一项（名称）必填；slug 留空由后端自动生成
const rules: FormRules = {
  [props.fields[0]?.key ?? 'name']: [
    { required: true, message: `请输入${props.label}名称`, trigger: 'blur' },
  ],
}

const emptyText = computed(() => `暂无${props.label}`)

function openCreate() {
  editing.value = null
  props.fields.forEach((field) => {
    form[field.key] = ''
  })
  dialogVisible.value = true
}

/** 按声明的字段从行回填表单；未声明的字段不带过去（如标签没有 description） */
function openEdit(row: CrudRow) {
  editing.value = row
  const source = row as unknown as Record<string, unknown>
  props.fields.forEach((field) => {
    const value = source[field.key]
    form[field.key] = value == null ? '' : String(value)
  })
  dialogVisible.value = true
}

async function handleSave() {
  saving.value = true
  try {
    await props.submit({ ...form }, editing.value)
    ElMessage.success('保存成功')
    dialogVisible.value = false
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
      `确定删除${props.label}「${row.name}」吗？`,
      '删除确认',
      { type: 'warning' },
    )
  } catch {
    return
  }
  try {
    await props.remove(row)
    ElMessage.success('删除成功')
    emit('changed')
  } catch (e) {
    ElMessage.error(errorMessage(e, '删除失败'))
  }
}
</script>

<template>
  <div>
    <h1 class="text-xl font-semibold">{{ title }}</h1>
    <div class="space-y-4">
      <el-button type="warning" @click="openCreate">新建{{ label }}</el-button>

      <div v-loading="loading" class="hidden overflow-x-auto md:block">
        <el-table :data="list" border stripe>
          <el-table-column
            v-for="col in columns"
            :key="col.prop"
            :prop="col.prop"
            :label="col.label"
            :width="col.width"
          />
          <el-table-column label="操作" width="140">
            <!-- el-table 作用域插槽的类型是 DefaultRow（无法收窄），沿用既有写法（FE-12） -->
            <template #default="{ row }: { row: any }">
              <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
              <el-button link type="danger" @click="handleDelete(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div v-loading="loading" class="space-y-3 md:hidden">
        <div
          v-for="row in list"
          :key="row.id"
          class="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-700 dark:bg-stone-900"
        >
          <div class="flex items-center justify-between gap-3">
            <span class="font-medium text-stone-900 dark:text-stone-100">{{ namePrefix }}{{ row.name }}</span>
            <span class="shrink-0 text-xs text-stone-400">{{ row.slug }}</span>
          </div>
          <p
            v-if="showDescription && row.description"
            class="mt-1 text-sm text-stone-500 dark:text-stone-400"
          >
            {{ row.description }}
          </p>
          <div class="mt-3 flex justify-end gap-2">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" @click="handleDelete(row)">删除</el-button>
          </div>
        </div>
        <div v-if="!loading && list.length === 0" class="py-8 text-center text-sm text-stone-400">
          {{ emptyText }}
        </div>
      </div>

      <el-dialog
        v-model="dialogVisible"
        :title="editing ? `编辑${label}` : `新建${label}`"
        width="min(90vw, 480px)"
      >
        <el-form :model="form" :rules="rules" label-position="top">
          <el-form-item v-for="field in fields" :key="field.key" :label="field.label" :prop="field.key">
            <el-input v-model="form[field.key]" :placeholder="field.placeholder" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="dialogVisible = false">取消</el-button>
          <el-button type="warning" :loading="saving" @click="handleSave">保存</el-button>
        </template>
      </el-dialog>
    </div>
  </div>
</template>