<script setup lang="ts">
import type { AdminArticleDetail, Category, Tag } from '~/types/api'

const props = defineProps<{
  initial?: AdminArticleDetail | null
  submitLabel: string
  categories: Category[]
  tags: Tag[]
  loading?: boolean
}>()

const emit = defineEmits<{ submit: [formData: FormData] }>()

const isCreateMode = computed(() => !props.initial)

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
  content: props.initial?.content ?? '',
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

const COVER_MAX_BYTES = 20 * 1024 * 1024
const ATTACHMENT_MAX_BYTES = 50 * 1024 * 1024

// 单文件"替换"语义：不用 el-upload 的 limit/on-exceed 拦截——当列表里已有文件
// （编辑模式预填的封面）时再选新文件会走 on-exceed 且不触发 on-change，新文件会被
// 静默丢弃。这里改为不设 limit，在 on-change 里只保留最新选中的那个。
function onCoverChange(file: any, files: any[]) {
  if (!file.raw) return
  if (file.raw.size > COVER_MAX_BYTES) {
    ElMessage.error('封面不能超过 20MB')
    coverList.value = files.filter((item) => item.uid !== file.uid)
    return
  }
  coverFile.value = file.raw
  coverList.value = [file]
}
function onAttachmentChange(file: any, files: any[]) {
  if (!file.raw) return
  if (file.raw.size > ATTACHMENT_MAX_BYTES) {
    ElMessage.error('附件不能超过 50MB')
    attachmentList.value = files.filter((item) => item.uid !== file.uid)
    return
  }
  attachmentFile.value = file.raw
  attachmentList.value = [file]
}
// 从列表里移除后不得再提交该文件（否则"删掉"仍会被上传）
function onCoverRemove() {
  coverFile.value = null
}
function onAttachmentRemove() {
  attachmentFile.value = null
}

/* ---------------------------------------------------------------- Markdown 正文 */

const contentRef = ref<any>(null)
const previewHtml = ref('')
const previewVisible = ref(false)
const previewing = ref(false)
const uploadingImage = ref(false)

const IMAGE_MAX_BYTES = 10 * 1024 * 1024

// 在光标处插入文本（不监听 v-model，避免长正文输入卡顿）
function insertAtCursor(text: string) {
  const el: HTMLTextAreaElement | undefined = contentRef.value?.textarea
  if (!el) {
    form.content += text
    return
  }
  const start = el.selectionStart ?? form.content.length
  const end = el.selectionEnd ?? start
  form.content = form.content.slice(0, start) + text + form.content.slice(end)
  nextTick(() => {
    el.focus()
    el.selectionStart = el.selectionEnd = start + text.length
  })
}

async function onInlineImageChange(file: any) {
  const raw: File | undefined = file?.raw
  if (!raw) return
  if (raw.size > IMAGE_MAX_BYTES) {
    ElMessage.error('图片不能超过 10MB')
    return
  }
  uploadingImage.value = true
  try {
    const fd = new FormData()
    fd.append('image', raw)
    const res = await useApi().uploadWithProgress<{ url: string; width: number; height: number }>(
      '/admin/articles/images/',
      fd,
    )
    insertAtCursor(`![${raw.name}](${res.data.url})`)
    ElMessage.success('图片已插入正文')
  } catch (e: any) {
    ElMessage.error(e?.data?.message ?? '图片上传失败')
  } finally {
    uploadingImage.value = false
  }
}

// 预览走服务端渲染（与线上同一条管线），保证"所见即所得"且不引入前端 markdown 依赖
async function handlePreview() {
  previewing.value = true
  try {
    const res = await useApi().post<{ content_html: string }>('/admin/articles/preview/', {
      content: form.content,
    })
    previewHtml.value = res.data.content_html
    previewVisible.value = true
  } catch (e: any) {
    ElMessage.error(e?.data?.message ?? '预览失败')
  } finally {
    previewing.value = false
  }
}

/* -------------------------------------------------------------------- 提交 */

function buildFormData(): FormData {
  const fd = new FormData()
  fd.append('title', form.title)
  if (form.slug.trim()) fd.append('slug', form.slug.trim())
  fd.append('summary', form.summary)
  fd.append('content', form.content)
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
  if (isCreateMode.value && coverList.value.length === 0) {
    ElMessage.error('请上传封面')
    return
  }
  // 附件可选，但「正文与附件至少填一项」（后端同样校验）
  if (!form.content.trim() && attachmentList.value.length === 0) {
    ElMessage.error('正文与附件至少填写一项')
    return
  }
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
    <el-form-item label="正文（Markdown，图片请用「插入图片」上传）">
      <el-input
        ref="contentRef"
        v-model="form.content"
        type="textarea"
        :rows="18"
        resize="vertical"
        class="font-mono"
        placeholder="支持 Markdown：# 标题、**加粗**、- 列表、```代码块```、| 表格 |"
      />
      <div class="mt-2 flex flex-wrap items-center gap-2">
        <el-upload
          :auto-upload="false"
          :show-file-list="false"
          :accept="'.jpg,.jpeg,.png,.webp'"
          :on-change="onInlineImageChange"
          :disabled="uploadingImage"
        >
          <el-button size="small" :loading="uploadingImage">插入图片</el-button>
        </el-upload>
        <el-button size="small" :loading="previewing" @click="handlePreview">
          {{ previewVisible ? '刷新预览' : '预览' }}
        </el-button>
        <el-button v-if="previewVisible" size="small" text @click="previewVisible = false">收起预览</el-button>
        <span class="text-xs text-stone-400">图片会压缩为 WebP（最长边 1920）后插入</span>
      </div>
    </el-form-item>
    <el-form-item v-if="previewVisible" label="预览（服务端渲染结果）">
      <div class="md-body w-full rounded-lg border border-stone-200 p-4 dark:border-stone-700" v-html="previewHtml" />
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
    <el-form-item label="封面（JPG/PNG/WebP ≤20MB）" :required="isCreateMode">
      <el-upload
        v-model:file-list="coverList"
        :auto-upload="false"
        :accept="'.jpg,.jpeg,.png,.webp'"
        :on-change="onCoverChange"
        :on-remove="onCoverRemove"
      >
        <el-button>选择封面</el-button>
      </el-upload>
    </el-form-item>
    <el-form-item label="附件（可选，PDF/Word ≤50MB）">
      <el-upload
        v-model:file-list="attachmentList"
        :auto-upload="false"
        :accept="'.pdf,.doc,.docx'"
        :on-change="onAttachmentChange"
        :on-remove="onAttachmentRemove"
      >
        <el-button>选择附件</el-button>
      </el-upload>
    </el-form-item>
    <el-button type="warning" :loading="loading" @click="handleSubmit">{{ submitLabel }}</el-button>
  </el-form>
</template>