<script setup lang="ts">
const colorMode = useColorMode()
const isDark = computed(() => colorMode.value === 'dark')
function toggleColorMode() {
  colorMode.preference = isDark.value ? 'light' : 'dark'
}

const navLinks = [
  { label: '首页', to: '/' },
  { label: '分类', to: '/categories' },
  { label: '标签', to: '/tags' },
  { label: '搜索', to: '/search' },
]
</script>

<template>
  <div class="flex min-h-screen flex-col bg-paper-light text-ink-light dark:bg-stone-900 dark:text-stone-100">
    <header class="sticky top-0 z-10 border-b border-stone-200 bg-paper-light/80 backdrop-blur dark:border-stone-800 dark:bg-stone-900/80">
      <div class="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
        <NuxtLink to="/" class="text-2xl font-serif font-bold tracking-wide text-brand-600 dark:text-amber-500">
          旅行游记
        </NuxtLink>
        <nav class="flex items-center gap-6">
          <NuxtLink
            v-for="link in navLinks"
            :key="link.to"
            :to="link.to"
            class="text-sm text-stone-600 transition-colors hover:text-brand-600 dark:text-stone-300 dark:hover:text-amber-400"
          >
            {{ link.label }}
          </NuxtLink>
          <button
            type="button"
            class="flex h-9 w-9 items-center justify-center rounded-full border border-stone-300 text-stone-600 transition-colors hover:border-brand-500 hover:text-brand-600 dark:border-stone-700 dark:text-stone-300 dark:hover:border-amber-500 dark:hover:text-amber-400"
            :aria-label="isDark ? '切换到亮色模式' : '切换到暗色模式'"
            @click="toggleColorMode"
          >
            <Icon :name="isDark ? 'lucide:sun' : 'lucide:moon'" class="h-5 w-5" />
          </button>
        </nav>
      </div>
    </header>

    <main class="mx-auto w-full max-w-5xl flex-1 px-6 py-8">
      <slot />
    </main>

    <footer class="border-t border-stone-200 py-6 text-center text-sm text-stone-500 dark:border-stone-800 dark:text-stone-400">
      © 2026 旅行游记 · 文艺 · 极简
    </footer>
  </div>
</template>
