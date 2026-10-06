<script setup lang="ts">
/** 亮/暗切换按钮：桌面端与移动端共用，仅 class 差异由 `hoverable` 控制（FE-24） */
const props = defineProps<{
  /** 桌面端（带 hover 反馈与 title 提示）；移动端传 false */
  hoverable?: boolean
}>()

const colorMode = useColorMode()
const isDark = computed(() => colorMode.value === 'dark')
const { isSkinActive } = useAppTheme()

const hoverable = computed(() => props.hoverable !== false)

function toggleColorMode() {
  if (isSkinActive.value) return
  colorMode.preference = isDark.value ? 'light' : 'dark'
}
</script>

<template>
  <button
    type="button"
    class="flex h-9 w-9 items-center justify-center rounded-full border transition-colors"
    :class="isSkinActive
      ? 'cursor-not-allowed border-stone-200 text-stone-300 dark:border-stone-800 dark:text-stone-600'
      : hoverable
        ? 'border-stone-300 text-stone-600 hover:border-brand-500 hover:text-brand-600 dark:border-stone-700 dark:text-stone-300 dark:hover:border-amber-500 dark:hover:text-amber-400'
        : 'border-stone-300 text-stone-600 dark:border-stone-700 dark:text-stone-300'"
    :disabled="isSkinActive"
    :aria-label="isSkinActive ? '当前风格下不可切换亮/暗' : (isDark ? '切换到亮色模式' : '切换到暗色模式')"
    :title="isSkinActive ? '当前风格下不可切换亮/暗' : (hoverable ? '切换亮/暗' : undefined)"
    @click="toggleColorMode"
  >
    <Icon :name="isDark ? 'lucide:sun' : 'lucide:moon'" class="h-5 w-5" />
  </button>
</template>