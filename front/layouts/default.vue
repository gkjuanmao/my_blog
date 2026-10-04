<script setup lang="ts">
const colorMode = useColorMode()
const isDark = computed(() => colorMode.value === 'dark')

const { skin, skinClass, isSkinActive } = useAppTheme()

// 皮肤动效（滚动揭示/卡片倾斜/按钮磁场），仅在非默认皮肤且非 reduced-motion 时生效
useSkinMotion()

// 皮肤类只作用于公开页（本布局）：
// SSR 直接输出（避免首屏闪烁）；客户端用 classList 同步，离开公开页时移除，后台 admin 不受影响
if (import.meta.server) {
  useHead({ htmlAttrs: { class: skinClass.value } })
} else {
  watchEffect(() => {
    const el = document.documentElement
    el.classList.toggle('skin-elegant', skin.value === 'elegant')
    el.classList.toggle('skin-neon', skin.value === 'neon')
  })
  onBeforeUnmount(() => document.documentElement.classList.remove('skin-elegant', 'skin-neon'))
}

function toggleColorMode() {
  if (isSkinActive.value) return
  colorMode.preference = isDark.value ? 'light' : 'dark'
}

const navLinks = [
  { label: '首页', to: '/' },
  { label: '分类', to: '/categories' },
  { label: '标签', to: '/tags' },
  { label: '搜索', to: '/search' },
]

const menuOpen = ref(false)
const route = useRoute()
watch(
  () => route.fullPath,
  () => {
    menuOpen.value = false
  },
)
</script>

<template>
  <div class="public-shell flex min-h-screen flex-col bg-paper-light text-ink-light dark:bg-stone-900 dark:text-stone-100">
    <header class="sticky top-0 z-10 border-b border-stone-200 bg-paper-light/80 backdrop-blur dark:border-stone-800 dark:bg-stone-900/80">
      <div class="mx-auto flex max-w-5xl items-center justify-between px-4 py-3 sm:px-6 sm:py-4">
        <NuxtLink to="/" class="text-xl font-serif font-bold tracking-wide text-brand-600 dark:text-amber-500 sm:text-2xl">
          旅行游记
        </NuxtLink>

        <nav class="hidden items-center gap-6 md:flex">
          <NuxtLink
            v-for="link in navLinks"
            :key="link.to"
            :to="link.to"
            class="text-sm text-stone-600 transition-colors hover:text-brand-600 dark:text-stone-300 dark:hover:text-amber-400"
          >
            {{ link.label }}
          </NuxtLink>
          <SkinSwitcher />
          <button
            type="button"
            class="flex h-9 w-9 items-center justify-center rounded-full border transition-colors"
            :class="isSkinActive
              ? 'cursor-not-allowed border-stone-200 text-stone-300 dark:border-stone-800 dark:text-stone-600'
              : 'border-stone-300 text-stone-600 hover:border-brand-500 hover:text-brand-600 dark:border-stone-700 dark:text-stone-300 dark:hover:border-amber-500 dark:hover:text-amber-400'"
            :disabled="isSkinActive"
            :aria-label="isSkinActive ? '当前风格下不可切换亮/暗' : (isDark ? '切换到亮色模式' : '切换到暗色模式')"
            :title="isSkinActive ? '当前风格下不可切换亮/暗' : '切换亮/暗'"
            @click="toggleColorMode"
          >
            <Icon :name="isDark ? 'lucide:sun' : 'lucide:moon'" class="h-5 w-5" />
          </button>
        </nav>

        <div class="flex items-center gap-2 md:hidden">
          <SkinSwitcher />
          <button
            type="button"
            class="flex h-9 w-9 items-center justify-center rounded-full border transition-colors"
            :class="isSkinActive
              ? 'cursor-not-allowed border-stone-200 text-stone-300 dark:border-stone-800 dark:text-stone-600'
              : 'border-stone-300 text-stone-600 dark:border-stone-700 dark:text-stone-300'"
            :disabled="isSkinActive"
            :aria-label="isSkinActive ? '当前风格下不可切换亮/暗' : (isDark ? '切换到亮色模式' : '切换到暗色模式')"
            @click="toggleColorMode"
          >
            <Icon :name="isDark ? 'lucide:sun' : 'lucide:moon'" class="h-5 w-5" />
          </button>
          <button
            type="button"
            class="flex h-9 w-9 items-center justify-center rounded-full border border-stone-300 text-stone-600 dark:border-stone-700 dark:text-stone-300"
            :aria-label="menuOpen ? '关闭菜单' : '打开菜单'"
            :aria-expanded="menuOpen"
            @click="menuOpen = !menuOpen"
          >
            <Icon :name="menuOpen ? 'lucide:x' : 'lucide:menu'" class="h-5 w-5" />
          </button>
        </div>
      </div>

      <nav v-if="menuOpen" class="border-t border-stone-200 px-4 py-2 dark:border-stone-800 md:hidden">
        <NuxtLink
          v-for="link in navLinks"
          :key="link.to"
          :to="link.to"
          class="block rounded-lg px-3 py-2.5 text-sm text-stone-600 transition-colors hover:bg-stone-100 hover:text-brand-600 dark:text-stone-300 dark:hover:bg-stone-800 dark:hover:text-amber-400"
        >
          {{ link.label }}
        </NuxtLink>
      </nav>
    </header>

    <main class="mx-auto w-full max-w-5xl flex-1 px-4 py-6 sm:px-6 sm:py-8">
      <slot />
    </main>

    <footer class="border-t border-stone-200 py-6 text-center text-sm text-stone-500 dark:border-stone-800 dark:text-stone-400">
      © 2026 旅行游记 · 文艺 · 极简
    </footer>
  </div>
</template>
