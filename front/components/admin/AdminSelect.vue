<script setup lang="ts">
/**
 * 后台下拉：自绘列表，替掉原生 <select>。
 *
 * 为什么不用原生 select：弹层是系统 UI（白底 + 蓝色高亮 + 系统字体），在纸面这套
 * 视觉里像贴了一张别处的截图；而且 option 无法承载「作者（36）」这种右侧数字。
 *
 * 交互按 combobox 模式：焦点始终留在触发器上，用 aria-activedescendant 指向当前项，
 * 键盘和读屏都不需要把焦点搬进浮层再搬回来。
 */
import type { SelectOption } from '~/types/admin'

const props = withDefaults(
  defineProps<{
    options: SelectOption[]
    /** 读屏用：这个下拉在筛什么 */
    label: string
    disabled?: boolean
  }>(),
  { disabled: false },
)

const value = defineModel<string>({ required: true })
const emit = defineEmits<{ change: [string] }>()

const uid = useId()
const rootRef = ref<HTMLElement | null>(null)
const open = ref(false)
const activeIndex = ref(-1)

const selectedIndex = computed(() => props.options.findIndex(option => option.value === value.value))
const selectedLabel = computed(() => props.options[selectedIndex.value]?.label ?? '请选择')
const isMuted = computed(() => props.options[selectedIndex.value]?.muted ?? false)

function onPointerDown(event: PointerEvent) {
  if (!rootRef.value?.contains(event.target as Node)) close()
}

function openPanel() {
  if (props.disabled || open.value) return
  open.value = true
  activeIndex.value = selectedIndex.value >= 0 ? selectedIndex.value : 0
  // 捕获阶段监听：浮层里的点击不会先冒泡到别处，避免刚开就被关掉
  document.addEventListener('pointerdown', onPointerDown, true)
}

function close() {
  open.value = false
  document.removeEventListener('pointerdown', onPointerDown, true)
}

function pick(index: number) {
  const option = props.options[index]
  if (!option) return
  if (option.value !== value.value) {
    value.value = option.value
    emit('change', option.value)
  }
  close()
}

function move(delta: number) {
  if (!open.value) {
    openPanel()
    return
  }
  const last = props.options.length - 1
  activeIndex.value = Math.min(last, Math.max(0, activeIndex.value + delta))
}

function onKeydown(event: KeyboardEvent) {
  if (props.disabled) return
  switch (event.key) {
    case 'ArrowDown':
      event.preventDefault()
      move(1)
      break
    case 'ArrowUp':
      event.preventDefault()
      move(-1)
      break
    case 'Home':
      if (!open.value) break
      event.preventDefault()
      activeIndex.value = 0
      break
    case 'End':
      if (!open.value) break
      event.preventDefault()
      activeIndex.value = props.options.length - 1
      break
    case 'Enter':
    case ' ':
      event.preventDefault()
      if (open.value) pick(activeIndex.value)
      else openPanel()
      break
    case 'Escape':
      if (!open.value) break
      event.preventDefault()
      close()
      break
    case 'Tab':
      if (open.value) close()
      break
  }
}

onBeforeUnmount(() => document.removeEventListener('pointerdown', onPointerDown, true))
</script>

<template>
  <div ref="rootRef" class="ad-select" :class="{ 'is-open': open, 'is-disabled': disabled }">
    <button
      type="button"
      class="ad-select__trigger"
      role="combobox"
      :aria-label="label"
      :aria-expanded="open"
      :aria-controls="`${uid}-list`"
      :aria-activedescendant="open && activeIndex >= 0 ? `${uid}-opt-${activeIndex}` : undefined"
      :disabled="disabled"
      @click="open ? close() : openPanel()"
      @keydown="onKeydown"
    >
      <span class="ad-select__value" :class="{ 'is-muted': isMuted }">{{ selectedLabel }}</span>
      <svg class="ad-select__chev" viewBox="0 0 10 6" aria-hidden="true">
        <path d="M1 1.2 5 4.8 9 1.2" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    </button>

    <ul v-if="open" :id="`${uid}-list`" class="ad-select__panel" role="listbox" :aria-label="label">
      <li v-if="!options.length" class="ad-select__empty">没有可选内容</li>
      <li
        v-for="(option, index) in options"
        :id="`${uid}-opt-${index}`"
        :key="option.value"
        class="ad-select__opt"
        :class="{ 'is-active': index === activeIndex, 'is-muted': option.muted }"
        role="option"
        :aria-selected="option.value === value"
        @click="pick(index)"
        @mousemove="activeIndex = index"
      >
        <span class="ad-select__label">{{ option.label }}</span>
        <span v-if="option.hint" class="ad-select__hint">{{ option.hint }}</span>
        <svg
          v-if="option.value === value"
          class="ad-select__tick"
          viewBox="0 0 12 10"
          aria-hidden="true"
        >
          <path d="M1 5.2 4.4 8.6 11 1.6" />
        </svg>
      </li>
    </ul>
  </div>
</template>
