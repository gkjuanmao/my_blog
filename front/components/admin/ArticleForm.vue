<script setup lang="ts">
import type { ArticleDetail, Category, Tag } from '~/types/api'

const props = defineProps<{
  initial?: ArticleDetail | null
  submitLabel: string
  categories: Category[]
  tags: Tag[]
  loading?: boolean
}>()

const emit = defineEmits<{ submit: [formData: FormData] }>()

function toPickerValue(iso?: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

const form = reactive({
  title: props.initial?.title ?? '',
  slug: props.initial?.slug ?? '',
  summary: props.initial?.summary ?? '',
  location: props.initial?.location ?? '',
  publish_time: toPickerValue(props.initial?.publish_time),
  category_id: (props.initial?.category?.id as number | null) ?? null,
  tag_ids: (props.initial?.tags?.map((t) => t.id) ?? []) as number[],
  is_published: props.initial?.is_published ?? false,
})

const rules = {
  title: [{ required: true, message: '请输入标题', trigger: 'blur' }],
  publish_time: [{ required: true, message: '请选择发布时间', trigger: 'change' }],
}

const coverFile = ref<File | null>(null)
const attachmentFile = ref<File | null>(null)
const coverList = ref<{ name: string; url?: string }[]>(
  props.initial?.cover_image_url ? [{ name: props.initial.cover_image_name, url: props.initial.cover_image_url }] : [],
)
const attachmentList = ref<{ name: string; url?: string }[]>(
  props.initial?.file_url ? [{ name: props.initial.file_name, url: props.initial.file_url }] : [],
)

function onCoverChange(file: any) {
  if (!file.raw) return
  coverFile.value = file.raw
  if (file.raw.size > 20 * 1024 * 1024) {
    ElMessage.error('封面不能超过 20MB')
    coverFile.value = null
    coverList.value = []
  }
}
function onCoverExceed() {
  coverList.value = []
  coverFile.value = null
}
function onAttachmentChange(file: any) {
  if (!file.raw) return
  attachmentFile.value = file.raw
  if (file.raw.size > 50 * 1024 * 1024) {
    ElMessage.error('附件不能超过 50MB')
    attachmentFile.value = null
    attachmentList.value = []
  }
}
function onAttachmentExceed() {
  attachmentList.value = []
  attachmentFile.value = null
}

function buildFormData(): FormData {
  const fd = new FormData()
  fd.append('title', form.title)
  if (form.slug.trim()) fd.append('slug', form.slug.trim())
  fd.append('summary', form.summary)
  fd.append('location', form.location)
  fd.append('publish_time', form.publish_time)
  if (form.category_id != null) fd.append('category_id', String(form.category_id))
  fd.append('tag_ids', JSON.stringify(form.tag_ids))
  fd.append('is_published', form.is_published ? 'true' : 'false')
  if (coverFile.value) fd.append('cover', coverFile.value)
  if (attachmentFile.value) fd.append('attachment', attachmentFile.value)
  return fd
}

function handleSubmit() {
  const fd = buildFormData()
  if ((coverFile.value?.size ?? 0) + (attachmentFile.value?.size ?? 0) > 60 * 1024 * 1024) {
    ElMessage.error('封面与附件合计不能超过 60MB')
    return
  }
  emit('submit', fd)
}
</script>

<template>
  <el-form :model="form" :rules="rules" label-position="top" class="max-w-2xl">
    <el-form-item label="标题" prop="title">
      <el-input v-model="form.title" placeholder="请输入标题" />
    </el-form-item>
    <el-form-item label="Slug（留空自动生成）">
      <el-input v-model="form.slug" placeholder="如 my-first-trip" />
    </el-form-item>
    <el-form-item label="摘要">
      <el-input v-model="form.summary" type="textarea" :rows="3" placeholder="请输入摘要" />
    </el-form-item>
    <el-form-item label="发布时间" prop="publish_time">
      <el-date-picker v-model="form.publish_time" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" placeholder="选择时间" style="width: 100%" />
    </el-form-item>
    <el-form-item label="地点">
      <el-input v-model="form.location" placeholder="如 云南 · 大理" />
    </el-form-item>
    <el-form-item label="分类">
      <el-select v-model="form.category_id" clearable placeholder="默认分类" style="width: 100%">
        <el-option v-for="c in categories" :key="c.id" :label="c.name" :value="c.id" />
      </el-select>
    </el-form-item>
    <el-form-item label="标签">
      <el-select v-model="form.tag_ids" multiple placeholder="选择标签" style="width: 100%">
        <el-option v-for="t in tags" :key="t.id" :label="t.name" :value="t.id" />
      </el-select>
    </el-form-item>
    <el-form-item label="是否发布">
      <el-switch v-model="form.is_published" active-text="发布" inactive-text="草稿" />
    </el-form-item>
    <el-form-item label="封面（JPG/PNG/WebP ≤20MB）">
      <el-upload
        v-model:file-list="coverList"
        :auto-upload="false"
        :limit="1"
        :accept="'.jpg,.jpeg,.png,.webp'"
        :on-change="onCoverChange"
        :on-exceed="onCoverExceed"
      >
        <el-button>选择封面</el-button>
      </el-upload>
    </el-form-item>
    <el-form-item label="附件（PDF/Word/HTML ≤50MB）">
      <el-upload
        v-model:file-list="attachmentList"
        :auto-upload="false"
        :limit="1"
        :accept="'.pdf,.doc,.docx,.html'"
        :on-change="onAttachmentChange"
        :on-exceed="onAttachmentExceed"
      >
        <el-button>选择附件</el-button>
      </el-upload>
    </el-form-item>
    <el-button type="warning" :loading="loading" @click="handleSubmit">{{ submitLabel }}</el-button>
  </el-form>
</template>
