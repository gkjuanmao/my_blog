<script setup lang="ts">
import type { Skin } from '~/composables/useAppTheme'

const { skin, switcherVisible, setSkin } = useAppTheme()

const options: { value: Skin; label: string }[] = [
  { value: 'default', label: '默认风格' },
  { value: 'elegant', label: '优雅（暖色）' },
  { value: 'neon', label: '赛博（霓虹）' },
]

function onCommand(command: string | number | object) {
  if (command === 'default' || command === 'elegant' || command === 'neon') setSkin(command)
}
</script>

<template>
  <el-dropdown v-if="switcherVisible" trigger="click" @command="onCommand">
    <button
      type="button"
      class="skin-switcher-btn flex h-9 w-9 items-center justify-center rounded-full border border-stone-300 text-stone-600 transition-colors hover:border-brand-500 hover:text-brand-600 dark:border-stone-700 dark:text-stone-300 dark:hover:border-amber-500 dark:hover:text-amber-400"
      aria-label="切换界面风格"
      title="切换界面风格"
    >
      <Icon name="lucide:palette" class="h-5 w-5" />
    </button>
    <template #dropdown>
      <el-dropdown-menu>
        <el-dropdown-item v-for="opt in options" :key="opt.value" :command="opt.value">
          <span :class="skin === opt.value ? 'font-semibold' : ''">{{ opt.label }}</span>
          <span v-if="skin === opt.value" class="ml-2 text-xs opacity-60">当前</span>
        </el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>