<script setup lang="ts">
import type { InputInstance, UploadFile } from 'element-plus'

import {
  API_UPLOAD_LIMIT_BYTES,
  ATTACHMENT_MAX_BYTES,
  COVER_MAX_BYTES,
  HTML_IMPORT_MAX_BYTES,
  INLINE_IMAGE_MAX_BYTES,
  INLINE_IMAGE_MAX_LONG_EDGE,
  formatMB,
} from '~/constants/uploads'
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

// 单文件"替换"语义：不用 el-upload 的 limit/on-exceed 拦截——当列表里已有文件
// （编辑模式预填的封面）时再选新文件会走 on-exceed 且不触发 on-change，新文件会被
// 静默丢弃。这里改为不设 limit，在 on-change 里只保留最新选中的那个。
function onCoverChange(file: UploadFile, files: UploadFile[]) {
  if (!file.raw) return
  if (file.raw.size > COVER_MAX_BYTES) {
    ElMessage.error(`封面不能超过 ${formatMB(COVER_MAX_BYTES)}`)
    coverList.value = files.filter((item) => item.uid !== file.uid)
    return
  }
  coverFile.value = file.raw
  coverList.value = [file]
}
function onAttachmentChange(file: UploadFile, files: UploadFile[]) {
  if (!file.raw) return
  if (file.raw.size > ATTACHMENT_MAX_BYTES) {
    ElMessage.error(`附件不能超过 ${formatMB(ATTACHMENT_MAX_BYTES)}`)
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

const contentRef = ref<InputInstance | null>(null)
const previewHtml = ref('')
const previewVisible = ref(false)
const previewing = ref(false)
const uploadingImage = ref(false)

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

async function onInlineImageChange(file: UploadFile) {
  const raw: File | undefined = file?.raw
  if (!raw) return
  if (raw.size > INLINE_IMAGE_MAX_BYTES) {
    ElMessage.error(`图片不能超过 ${formatMB(INLINE_IMAGE_MAX_BYTES)}`)
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
  } catch (e) {
    ElMessage.error(errorMessage(e, '图片上传失败'))
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
  } catch (e) {
    ElMessage.error(errorMessage(e, '预览失败'))
  } finally {
    previewing.value = false
  }
}

/* ---------------------------------------------------------------- 导入 HTML */

const htmlImportVisible = ref(false)
const htmlImporting = ref(false)
const htmlPaste = ref('')
const htmlFile = ref<File | null>(null)
const htmlWarnings = ref<string[]>([])

function openHtmlImport() {
  htmlPaste.value = ''
  htmlFile.value = null
  htmlWarnings.value = []
  htmlImportVisible.value = true
}

function onHtmlFileChange(file: UploadFile) {
  htmlFile.value = file?.raw ?? null
}

// 手机/第三方导出的 HTML → Markdown（服务端转换：base64 内嵌图压成 WebP 后落盘）
async function handleHtmlImport() {
  if (!htmlFile.value && !htmlPaste.value.trim()) {
    ElMessage.warning('请选择 HTML 文件或粘贴 HTML 内容')
    return
  }
  if (form.content.trim()) {
    try {
      await ElMessageBox.confirm('导入会覆盖当前正文，确定继续？', '覆盖确认', { type: 'warning' })
    } catch {
      return
    }
  }

  htmlImporting.value = true
  try {
    const fd = new FormData()
    if (htmlFile.value) fd.append('file', htmlFile.value)
    else fd.append('html', htmlPaste.value)

    const res = await useApi().post<{
      markdown: string
      images: number
      warnings: string[]
      suggested_title: string
    }>('/admin/articles/convert-html/', fd)
    form.content = res.data.markdown
    htmlWarnings.value = res.data.warnings
    // 便签导出的正文里没有标题，标题只在文件名里；仅在标题为空时回填，不覆盖已填内容
    if (res.data.suggested_title && !form.title.trim()) {
      form.title = res.data.suggested_title
    }
    // 有告警时保持对话框打开，让用户在关闭前看到提示（不可访问的图片等）
    if (!res.data.warnings.length) {
      htmlImportVisible.value = false
      ElMessage.success(res.data.images > 0 ? `已导入正文与 ${res.data.images} 张图片` : '已导入正文')
    }
    await handlePreview()
  } catch (e) {
    ElMessage.error(errorMessage(e, 'HTML 转换失败'))
  } finally {
    htmlImporting.value = false
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
  if ((coverFile.value?.size ?? 0) + (attachmentFile.value?.size ?? 0) > API_UPLOAD_LIMIT_BYTES) {
    ElMessage.error(`封面与附件合计不能超过 ${formatMB(API_UPLOAD_LIMIT_BYTES)}`)
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
        <el-button size="small" @click="openHtmlImport">导入 HTML</el-button>
        <el-button v-if="previewVisible" size="small" text @click="previewVisible = false">收起预览</el-button>
        <span class="text-xs text-stone-400">图片会压缩为 WebP（最长边 {{ INLINE_IMAGE_MAX_LONG_EDGE }}）后插入</span>
      </div>
    </el-form-item>
    <el-form-item v-if="previewVisible" label="预览（服务端渲染结果）">
      <!-- 限高 + 内部滚动：长正文预览不会把后面的表单字段顶到很下面 -->
      <div
        class="md-body max-h-[32rem] w-full overflow-y-auto overscroll-contain rounded-lg border border-stone-200 p-4 dark:border-stone-700"
        v-html="previewHtml"
      />
    </el-form-item>

    <el-dialog v-model="htmlImportVisible" title="导入 HTML 并转为 Markdown" width="640px">
      <el-alert
        v-if="htmlWarnings.length"
        type="warning"
        :closable="false"
        title="导入完成，以下内容需要你留意："
      >
        <ul class="mt-1 list-disc pl-4 text-xs">
          <li v-for="(w, index) in htmlWarnings" :key="index">{{ w }}</li>
        </ul>
      </el-alert>

      <el-form-item label="选择 HTML 文件" class="mt-3">
        <el-upload
          :auto-upload="false"
          :show-file-list="true"
          :limit="1"
          accept=".html,.htm"
          :on-change="onHtmlFileChange"
        >
          <el-button size="small">选择文件</el-button>
        </el-upload>
      </el-form-item>
      <el-form-item label="或粘贴 HTML">
        <el-input
          v-model="htmlPaste"
          type="textarea"
          :rows="8"
          resize="vertical"
          class="font-mono"
          placeholder="把手机导出的 HTML 源码粘贴到这里"
        />
      </el-form-item>
      <p class="text-xs text-stone-400">
        正文里的 base64 内嵌图会压缩为 WebP 并按内容寻址落盘（同图自动去重），外链图保留原样；
        标题为空时会用文件名（去掉时间戳后缀）自动填入；单个 HTML 文件最大 {{ formatMB(HTML_IMPORT_MAX_BYTES) }}。
      </p>
      <template #footer>
        <el-button @click="htmlImportVisible = false">关闭</el-button>
        <el-button type="primary" :loading="htmlImporting" @click="handleHtmlImport">
          导入并覆盖正文
        </el-button>
      </template>
    </el-dialog>
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
    <el-form-item :label="`封面（JPG/PNG/WebP ≤${formatMB(COVER_MAX_BYTES)}）`" :required="isCreateMode">
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
    <el-form-item :label="`附件（可选，PDF/Word ≤${formatMB(ATTACHMENT_MAX_BYTES)}）`">
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