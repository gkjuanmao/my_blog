<script setup lang="ts">
import VuePdfEmbed from 'vue-pdf-embed'
import 'vue-pdf-embed/dist/styles/annotationLayer.css'
import 'vue-pdf-embed/dist/styles/textLayer.css'

const props = defineProps<{ pdfUrl: string }>()

const page = ref(1)
const pageCount = ref(0)
const loading = ref(true)
const errorMsg = ref('')
const zoom = ref(100)
const zoomOptions = [50, 75, 100, 125, 150]

const pdfWidth = computed(() => Math.round(800 * (zoom.value / 100)))

function onLoaded(doc: { numPages: number }) {
  pageCount.value = doc.numPages
  loading.value = false
}
function onLoadingFailed(e: unknown) {
  errorMsg.value = (e as Error)?.message ?? 'PDF 加载失败'
  loading.value = false
}
function onRenderingFailed() {
  errorMsg.value = 'PDF 渲染失败'
  loading.value = false
}
function onPasswordRequested() {
  errorMsg.value = '该 PDF 受密码保护，无法预览'
  loading.value = false
}
function prevPage() {
  if (page.value > 1) page.value--
}
function nextPage() {
  if (page.value < pageCount.value) page.value++
}
function goToPage() {
  const n = Math.min(Math.max(1, page.value), pageCount.value || 1)
  page.value = n
}

watch(
  () => props.pdfUrl,
  () => {
    page.value = 1
    pageCount.value = 0
    loading.value = true
    errorMsg.value = ''
  },
)
</script>

<template>
  <div class="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-700 dark:bg-stone-900">
    <div class="mb-3 flex flex-wrap items-center justify-between gap-3">
      <div class="flex items-center gap-2 text-sm">
        <button
          class="rounded-md border border-stone-300 px-2.5 py-1 disabled:opacity-40 dark:border-stone-600"
          :disabled="page <= 1 || loading"
          @click="prevPage"
        >
          上一页
        </button>
        <span class="text-stone-600 dark:text-stone-300">{{ page }} / {{ pageCount || '—' }}</span>
        <button
          class="rounded-md border border-stone-300 px-2.5 py-1 disabled:opacity-40 dark:border-stone-600"
          :disabled="page >= pageCount || loading"
          @click="nextPage"
        >
          下一页
        </button>
      </div>
      <div class="flex items-center gap-2 text-sm">
        <select
          v-model.number="zoom"
          class="rounded-md border border-stone-300 bg-white px-2 py-1 dark:border-stone-600 dark:bg-stone-800"
        >
          <option v-for="z in zoomOptions" :key="z" :value="z">{{ z }}%</option>
        </select>
      </div>
    </div>

    <div v-if="loading && !errorMsg" class="py-12 text-center text-sm text-stone-400">PDF 加载中…</div>
    <div v-if="errorMsg" class="rounded-lg bg-red-50 py-12 text-center text-sm text-red-600 dark:bg-red-950/40 dark:text-red-400">
      {{ errorMsg }}
    </div>
    <ClientOnly v-if="pdfUrl && !errorMsg">
      <VuePdfEmbed
        :source="pdfUrl"
        :page="page"
        :width="pdfWidth"
        text-layer
        @loaded="onLoaded"
        @loading-failed="onLoadingFailed"
        @rendering-failed="onRenderingFailed"
        @password-requested="onPasswordRequested"
      />
      <template #fallback>
        <div class="py-12 text-center text-sm text-stone-400">PDF 组件加载中…</div>
      </template>
    </ClientOnly>
  </div>
</template>
