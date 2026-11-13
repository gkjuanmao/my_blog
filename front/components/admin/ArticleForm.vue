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

/** 内联校验：表单很短，直接给字段错误，不引入 el-form 的 label 结构 */
const errors = reactive({ title: '', publish_time: '', cover: '', content: '' })
const titleRef = ref<HTMLInputElement | null>(null)

/* ------------------------------------------------------------------ 上传 */

const coverFile = ref<File | null>(null)
const attachmentFile = ref<File | null>(null)
const coverList = ref<{ name: string; url?: string }[]>(
  props.initial?.cover_image_url ? [{ name: props.initial.cover_image_name, url: props.initial.cover_image_url }] : [],
)
const attachmentList = ref<{ name: string; url?: string; size?: number }[]>(
  props.initial?.file_url
    ? [{ name: props.initial.file_name, url: props.initial.file_url }]
    : [],
)

/** 封面预览：既有封面用后端 URL，新选文件用 object URL */
const coverPreview = ref(props.initial?.cover_image_url ?? '')
let previewBlob: string | null = null

function setCoverPreview(url: string) {
  if (previewBlob) URL.revokeObjectURL(previewBlob)
  previewBlob = url.startsWith('blob:') ? url : null
  coverPreview.value = url
}

onBeforeUnmount(() => {
  if (previewBlob) URL.revokeObjectURL(previewBlob)
})

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
  errors.cover = ''
  setCoverPreview(URL.createObjectURL(file.raw))
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
  errors.content = ''
}
// 从列表里移除后不得再提交该文件（否则"删掉"仍会被上传）
function onCoverRemove() {
  coverFile.value = null
}
function onAttachmentRemove() {
  attachmentFile.value = null
}
function clearCover() {
  coverList.value = []
  onCoverRemove()
  setCoverPreview('')
}
function clearAttachment() {
  attachmentList.value = []
  onAttachmentRemove()
}

/* -------------------------------------------------------------- 校验（内联） */

function validate(): boolean {
  errors.title = form.title.trim() ? '' : '请填写标题'
  errors.publish_time = form.publish_time ? '' : '请选择发布时间'
  errors.cover =
    isCreateMode.value && !coverFile.value && !coverList.value.length ? '请选择封面' : ''
  errors.content =
    !form.content.trim() && !attachmentList.value.length ? '正文与附件至少填写一项' : ''

  if (errors.title) {
    titleRef.value?.focus()
    return false
  }
  return !errors.publish_time && !errors.cover && !errors.content
}

/** 正文字数（去掉空白，按字符计，中文一格一字） */
const wordCount = computed(() => form.content.replace(/\s/g, '').length)

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
  if (!validate()) return
  const fd = buildFormData()
  if ((coverFile.value?.size ?? 0) + (attachmentFile.value?.size ?? 0) > API_UPLOAD_LIMIT_BYTES) {
    ElMessage.error(`封面与附件合计不能超过 ${formatMB(API_UPLOAD_LIMIT_BYTES)}`)
    return
  }
  emit('submit', fd)
}

function formatSize(bytes?: number): string {
  if (!bytes) return ''
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${Math.max(1, Math.round(bytes / 1024))} KB`
}
</script>

<template>
  <form class="ad-editor" novalidate @submit.prevent="handleSubmit">
    <!-- 主栏：标题 → slug → 摘要 → 正文 -->
    <div class="ad-editor__main">
      <div class="ad-title">
        <label class="ad-sr" for="ad-article-title">标题</label>
        <input
          id="ad-article-title"
          ref="titleRef"
          v-model="form.title"
          type="text"
          placeholder="无标题"
          :aria-invalid="errors.title ? 'true' : undefined"
          @input="errors.title = ''"
        >
        <span v-if="errors.title" class="ad-error">{{ errors.title }}</span>
      </div>

      <div class="ad-slugrow">
        <span>slug</span>
        <input v-model="form.slug" type="text" placeholder="留空由标题自动生成拼音">
      </div>

      <div class="ad-efield">
        <p class="ad-efield__label">摘要 <em>SUMMARY</em></p>
        <el-input
          v-model="form.summary"
          type="textarea"
          :rows="3"
          resize="none"
          placeholder="一两句话交代这段旅程，会出现在卡片和搜索结果里"
        />
      </div>

      <div class="ad-efield">
        <p class="ad-efield__label">
          正文 <em>MARKDOWN · {{ wordCount.toLocaleString() }} 字</em>
        </p>
        <el-input
          ref="contentRef"
          v-model="form.content"
          type="textarea"
          :rows="20"
          resize="vertical"
          class="ad-md"
          placeholder="支持 Markdown：# 标题、**加粗**、- 列表、```代码块```、| 表格 |"
          @input="errors.content = ''"
        />
        <p v-if="errors.content" class="ad-error" style="margin-top: 6px">{{ errors.content }}</p>

        <div class="ad-efield__tools">
          <el-upload
            :auto-upload="false"
            :show-file-list="false"
            :accept="'.jpg,.jpeg,.png,.webp'"
            :on-change="onInlineImageChange"
            :disabled="uploadingImage"
            style="width: auto"
          >
            <button class="ad-btn ad-btn--ghost ad-btn--sm" type="button" :disabled="uploadingImage">
              {{ uploadingImage ? '上传中…' : '插入图片' }}
            </button>
          </el-upload>
          <button class="ad-btn ad-btn--ghost ad-btn--sm" type="button" :disabled="previewing" @click="handlePreview">
            {{ previewing ? '渲染中…' : previewVisible ? '刷新清样' : '预览' }}
          </button>
          <button class="ad-btn ad-btn--ghost ad-btn--sm" type="button" @click="openHtmlImport">
            导入 HTML
          </button>
          <span class="ad-efield__hint">
            插图压缩为 WebP（最长边 {{ INLINE_IMAGE_MAX_LONG_EDGE }}）后插入
          </span>
        </div>

        <div v-if="previewVisible" class="ad-proof">
          <div class="ad-proof__head">
            清样 <span style="font-family: var(--hp-font-mono); letter-spacing: 0.04em">PROOF</span>
            <button class="ad-link" type="button" @click="previewVisible = false">收起</button>
          </div>
          <!-- 预览 HTML 由后端 /admin/articles/preview/ 渲染并经 nh3 消毒（跨多行，
               故用 disable/enable 块而非 disable-next-line） -->
          <!-- eslint-disable vue/no-v-html -->
          <div class="ad-proof__body md-body" v-html="previewHtml" />
          <!-- eslint-enable vue/no-v-html -->
        </div>
      </div>
    </div>

    <!-- 侧栏：发布设置 → 封面 → 附件 -->
    <aside class="ad-editor__aside">
      <section class="ad-aside-card">
        <h3>发布设置</h3>

        <div class="ad-aside-field">
          <p class="ad-efield__label">状态</p>
          <div class="ad-segs" role="group" aria-label="发布状态">
            <button
              class="ad-seg"
              type="button"
              :aria-pressed="!form.is_published"
              @click="form.is_published = false"
            >
              草稿
            </button>
            <button
              class="ad-seg"
              type="button"
              :aria-pressed="form.is_published"
              @click="form.is_published = true"
            >
              已发布
            </button>
          </div>
        </div>

        <div class="ad-aside-field">
          <p class="ad-efield__label">发布时间</p>
          <el-date-picker
            v-model="form.publish_time"
            type="datetime"
            format="YYYY-MM-DD HH:mm"
            value-format="YYYY-MM-DDTHH:mm:ss"
            placeholder="选择时间"
            style="width: 100%"
            @change="errors.publish_time = ''"
          />
          <span v-if="errors.publish_time" class="ad-error">{{ errors.publish_time }}</span>
        </div>

        <div class="ad-aside-field">
          <p class="ad-efield__label">栏目</p>
          <el-select v-model="form.category_id" clearable placeholder="默认分类" style="width: 100%">
            <el-option v-for="c in categories" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </div>

        <div class="ad-aside-field">
          <p class="ad-efield__label">标签</p>
          <el-select
            v-model="form.tag_ids"
            multiple
            collapse-tags
            collapse-tags-tooltip
            placeholder="选择标签"
            style="width: 100%"
          >
            <el-option v-for="t in tags" :key="t.id" :label="t.name" :value="t.id" />
          </el-select>
        </div>

        <div class="ad-aside-field">
          <p class="ad-efield__label">地点</p>
          <el-input v-model="form.location" placeholder="如 云南 · 大理" />
        </div>
      </section>

      <section class="ad-aside-card">
        <h3>封面</h3>
        <el-upload
          :auto-upload="false"
          :show-file-list="false"
          :accept="'.jpg,.jpeg,.png,.webp'"
          :on-change="onCoverChange"
        >
          <div class="ad-cover">
            <img v-if="coverPreview" :src="coverPreview" alt="封面预览">
            <span v-else class="ad-cover__empty">点击选择封面图片</span>
          </div>
        </el-upload>
        <div class="ad-cover__acts">
          <span class="ad-hint">JPG / PNG / WebP，≤{{ formatMB(COVER_MAX_BYTES) }}，自动压成 WebP</span>
          <button v-if="coverPreview" class="ad-link" type="button" @click="clearCover">移除</button>
        </div>
        <p v-if="errors.cover" class="ad-error" style="margin-top: 4px">{{ errors.cover }}</p>
      </section>

      <section class="ad-aside-card">
        <h3>附件</h3>
        <div v-if="attachmentList.length" class="ad-file" style="margin-bottom: 10px">
          <span class="ad-file__name">{{ attachmentList[0]?.name }}</span>
          <span v-if="attachmentList[0]?.size" class="ad-file__meta">
            {{ formatSize(attachmentList[0]?.size) }}
          </span>
          <a
            v-if="attachmentList[0]?.url"
            class="ad-link"
            :href="attachmentList[0]?.url"
            target="_blank"
            rel="noopener"
          >
            下载
          </a>
          <button class="ad-link ad-link--danger" type="button" @click="clearAttachment">移除</button>
        </div>
        <el-upload
          :auto-upload="false"
          :show-file-list="false"
          :accept="'.pdf,.doc,.docx'"
          :on-change="onAttachmentChange"
        >
          <button class="ad-btn ad-btn--ghost ad-btn--sm" type="button">
            {{ attachmentList.length ? '替换附件' : '选择附件' }}
          </button>
        </el-upload>
        <p class="ad-hint" style="margin-top: 8px">
          可选，PDF / Word ≤{{ formatMB(ATTACHMENT_MAX_BYTES) }}；正文与附件至少填一项。
        </p>
      </section>
    </aside>

    <!-- 粘底动作条：滚动时始终可达 -->
    <div class="ad-editor__foot">
      <p class="ad-editor__foot-meta">
        {{ form.is_published ? '已发布' : '草稿' }} · {{ wordCount.toLocaleString() }} 字
        <template v-if="form.slug"> · {{ form.slug }}</template>
      </p>
      <div class="ad-editor__foot-acts">
        <NuxtLink class="ad-btn ad-btn--text" to="/administrator/articles">取消</NuxtLink>
        <button class="ad-btn ad-btn--primary" type="submit" :disabled="loading">
          {{ loading ? '保存中…' : submitLabel }}
        </button>
      </div>
    </div>

    <el-dialog v-model="htmlImportVisible" title="导入 HTML 并转为 Markdown" width="min(640px, 94vw)">
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

      <div class="ad-field" style="margin-top: 16px">
        <span>选择 HTML 文件</span>
        <el-upload
          :auto-upload="false"
          :show-file-list="true"
          :limit="1"
          accept=".html,.htm"
          :on-change="onHtmlFileChange"
        >
          <button class="ad-btn ad-btn--ghost ad-btn--sm" type="button">选择文件</button>
        </el-upload>
      </div>
      <div class="ad-field" style="margin-top: 18px">
        <span>或粘贴 HTML</span>
        <el-input
          v-model="htmlPaste"
          type="textarea"
          :rows="8"
          resize="vertical"
          placeholder="把手机导出的 HTML 源码粘贴到这里"
        />
      </div>
      <p class="ad-hint" style="margin-top: 12px">
        正文里的 base64 内嵌图会压缩为 WebP 并按内容寻址落盘（同图自动去重），外链图保留原样；
        标题为空时会用文件名（去掉时间戳后缀）自动填入；单个 HTML 文件最大
        {{ formatMB(HTML_IMPORT_MAX_BYTES) }}。
      </p>
      <template #footer>
        <el-button @click="htmlImportVisible = false">关闭</el-button>
        <el-button type="primary" :loading="htmlImporting" @click="handleHtmlImport">
          导入并覆盖正文
        </el-button>
      </template>
    </el-dialog>
  </form>
</template>
