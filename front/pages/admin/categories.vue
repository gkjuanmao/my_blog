<script setup lang="ts">
import type { Category } from '~/types/api'

definePageMeta({ layout: 'admin' })

const list = ref<Category[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const editing = ref<Category | null>(null)
const form = reactive({ name: '', slug: '', description: '' })
const rules = { name: [{ required: true, message: '请输入分类名称', trigger: 'blur' }] }
const saving = ref(false)

async function fetchList() {
  loading.value = true
  try {
    const { data } = await useApi().get<Category[]>('/categories/')
    list.value = data
  } catch (e: any) {
    ElMessage.error(e?.data?.message ?? '加载失败')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = null
  form.name = ''; form.slug = ''; form.description = ''
  dialogVisible.value = true
}
function openEdit(row: Category) {
  editing.value = row
  form.name = row.name; form.slug = row.slug; form.description = row.description
  dialogVisible.value = true
}
async function handleSave() {
  saving.value = true
  try {
    if (editing.value) {
      await useApi().put(`/admin/categories/${editing.value.id}/`, { name: form.name, slug: form.slug, description: form.description })
    } else {
      await useApi().post('/admin/categories/', { name: form.name, slug: form.slug, description: form.description })
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
async function handleDelete(row: Category) {
  try {
    await ElMessageBox.confirm(`确定删除分类「${row.name}」吗？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await useApi().del(`/admin/categories/${row.id}/`)
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
    <h1 class="text-xl font-semibold">分类管理</h1>
    <div class="space-y-4">
      <el-button type="warning" @click="openCreate">新建分类</el-button>
      <el-table :data="list" v-loading="loading" border stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="slug" label="Slug" />
        <el-table-column prop="description" label="描述" />
        <el-table-column label="操作" width="140">
          <template #default="{ row }: { row: any }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-dialog v-model="dialogVisible" :title="editing ? '编辑分类' : '新建分类'" width="480">
        <el-form :model="form" :rules="rules" label-position="top">
          <el-form-item label="名称" prop="name">
            <el-input v-model="form.name" placeholder="请输入名称" />
          </el-form-item>
          <el-form-item label="Slug（留空自动生成）">
            <el-input v-model="form.slug" placeholder="如 travel" />
          </el-form-item>
          <el-form-item label="描述">
            <el-input v-model="form.description" placeholder="可选" />
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
