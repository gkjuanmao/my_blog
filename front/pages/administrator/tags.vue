<script setup lang="ts">
import type { Tag } from '~/types/api'

definePageMeta({ layout: 'admin' })

const list = ref<Tag[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const editing = ref<Tag | null>(null)
const form = reactive({ name: '', slug: '' })
const rules = { name: [{ required: true, message: '请输入标签名称', trigger: 'blur' }] }
const saving = ref(false)

async function fetchList() {
  loading.value = true
  try {
    const { data } = await useApi().get<Tag[]>('/tags/')
    list.value = data
  } catch (e: any) {
    ElMessage.error(e?.data?.message ?? '加载失败')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = null
  form.name = ''; form.slug = ''
  dialogVisible.value = true
}
function openEdit(row: Tag) {
  editing.value = row
  form.name = row.name; form.slug = row.slug
  dialogVisible.value = true
}
async function handleSave() {
  saving.value = true
  try {
    if (editing.value) {
      await useApi().put(`/admin/tags/${editing.value.id}/`, { name: form.name, slug: form.slug })
    } else {
      await useApi().post('/admin/tags/', { name: form.name, slug: form.slug })
    }
    ElMessage.success('保存成功')
    dialogVisible.value = false
    fetchList()
  } catch (e: any) {
    ElMessage.error(e?.data?.message ?? '保存失败')
  } finally {
    saving.value = false
  }
}
async function handleDelete(row: Tag) {
  try {
    await ElMessageBox.confirm(`确定删除标签「${row.name}」吗？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await useApi().del(`/admin/tags/${row.id}/`)
    ElMessage.success('删除成功')
    fetchList()
  } catch (e: any) {
    ElMessage.error(e?.data?.message ?? '删除失败')
  }
}

onMounted(fetchList)
</script>

<template>
  <div>
    <h1 class="text-xl font-semibold">标签管理</h1>
    <div class="space-y-4">
      <el-button type="warning" @click="openCreate">新建标签</el-button>

      <div v-loading="loading" class="hidden overflow-x-auto md:block">
        <el-table :data="list" border stripe>
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="name" label="名称" />
          <el-table-column prop="slug" label="Slug" />
          <el-table-column label="操作" width="140">
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
            <span class="font-medium text-stone-900 dark:text-stone-100"># {{ row.name }}</span>
            <span class="shrink-0 text-xs text-stone-400">{{ row.slug }}</span>
          </div>
          <div class="mt-3 flex justify-end gap-2">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" @click="handleDelete(row)">删除</el-button>
          </div>
        </div>
        <div v-if="!loading && list.length === 0" class="py-8 text-center text-sm text-stone-400">暂无标签</div>
      </div>

      <el-dialog v-model="dialogVisible" :title="editing ? '编辑标签' : '新建标签'" width="min(90vw, 480px)">
        <el-form :model="form" :rules="rules" label-position="top">
          <el-form-item label="名称" prop="name">
            <el-input v-model="form.name" placeholder="请输入名称" />
          </el-form-item>
          <el-form-item label="Slug（留空自动生成）">
            <el-input v-model="form.slug" placeholder="如 travel" />
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
