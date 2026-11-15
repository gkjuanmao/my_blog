<script setup lang="ts">
/**
 * 后台下拉：自绘列表，替掉原生 <select>。
 *
 * 为什么不用原生 select：弹层是系统 UI（白底 + 蓝色高亮 + 系统字体），在纸面这套
 * 视觉里像贴了一张别处的截图；而且 option 无法承载「作者 36」这种右侧数字。
 *
 * 两个必须写对的细节：
 * 1. 浮层 teleport 到 body 并按 fixed 定位——后台的侧栏、抽屉都是可滚动容器，
 *    留在原地会被 overflow 直接切掉（用户面板的角色/转移目标就在这种容器里）。
 * 2. 下方放不下就向上开：页脚的「每页 N 篇」贴着窗口底边，向下开只露出 7px。
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
    /** box = 工具带里的方框控件；inline = 嵌在句子里的小下拉（页脚「每页 N 篇」） */
    variant?: 'box' | 'inline'
    disabled?: boolean
  }>(),
  { variant: 'box', disabled: false },
)

const value = defineModel<string>({ required: true })
const emit = defineEmits<{ change: [string] }>()

const PANEL_GAP = 6
const PANEL_MAX_H = 268
const PANEL_MIN_W = 132

const uid = useId()
const rootRef = ref<HTMLElement | null>(null)
const triggerRef = ref<HTMLButtonElement | null>(null)
const panelRef = ref<HTMLElement | null>(null)
const open = ref(false)
const activeIndex = ref(-1)
/** 浮层摆位：fixed 坐标 + 可用高度（向上开时高度要按上方的空间算） */
const box = ref({ top: 0, left: 0, width: 0, maxHeight: PANEL_MAX_H })

const selectedIndex = computed(() => props.options.findIndex(option => option.value === value.value))
const selectedLabel = computed(() => props.options[selectedIndex.value]?.label ?? '请选择')
const isMuted = computed(() => props.options[selectedIndex.value]?.muted ?? false)

function onPointerDown(event: PointerEvent) {
  const target = event.target as Node
  // 浮层已 teleport 出去，不在 root 里，要单独判
  if (rootRef.value?.contains(target) || panelRef.value?.contains(target)) return
  close()
}

/** 按触发器与视口算一次位置：优先向下，下方不够且上方更宽裕则向上 */
function place() {
  const trigger = triggerRef.value
  if (!trigger) return
  const rect = trigger.getBoundingClientRect()
  const width = Math.max(rect.width, PANEL_MIN_W)
  const panelHeight = panelRef.value?.offsetHeight ?? PANEL_MAX_H

  const below = window.innerHeight - rect.bottom - PANEL_GAP - 8
  const above = rect.top - PANEL_GAP - 8
  const flip = below < panelHeight && above > below
  const maxHeight = Math.max(120, Math.min(PANEL_MAX_H, flip ? above : below))
  const height = Math.min(panelHeight, maxHeight)

  box.value = {
    top: flip ? Math.max(8, rect.top - PANEL_GAP - height) : rect.bottom + PANEL_GAP,
    left: Math.min(rect.left, window.innerWidth - width - 8),
    width,
    maxHeight,
  }
}

async function openPanel() {
  if (props.disabled || open.value) return
  open.value = true
  activeIndex.value = selectedIndex.value >= 0 ? selectedIndex.value : 0
  document.addEventListener('pointerdown', onPointerDown, true)
  window.addEventListener('scroll', place, true)
  window.addEventListener('resize', place)

  await nextTick()
  place()
  // 首帧量到的高度可能因 maxHeight 变化，再校一次
  await nextTick()
  place()
}

function close() {
  open.value = false
  document.removeEventListener('pointerdown', onPointerDown, true)
  window.removeEventListener('scroll', place, true)
  window.removeEventListener('resize', place)
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
    void openPanel()
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
      else void openPanel()
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

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onPointerDown, true)
  window.removeEventListener('scroll', place, true)
  window.removeEventListener('resize', place)
})
</script>

<template>
  <div ref="rootRef" class="ad-select" :class="[`ad-select--${variant}`, { 'is-open': open, 'is-disabled': disabled }]">
    <button
      ref="triggerRef"
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

    <Teleport to="body">
      <ul
        v-if="open"
        :id="`${uid}-list`"
        ref="panelRef"
        class="ad-select__panel"
        role="listbox"
        :aria-label="label"
        :style="{ top: `${box.top}px`, left: `${box.left}px`, width: `${box.width}px`, maxHeight: `${box.maxHeight}px` }"
      >
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
          <svg v-if="option.value === value" class="ad-select__tick" viewBox="0 0 12 10" aria-hidden="true">
            <path d="M1 5.2 4.4 8.6 11 1.6" />
          </svg>
        </li>
      </ul>
    </Teleport>
  </div>
</template>
