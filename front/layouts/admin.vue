<script setup lang="ts">
const { site } = useAppConfig()

const navItems = [
  { label: '仪表盘', to: '/administrator' },
  { label: '文章管理', to: '/administrator/articles' },
  { label: '分类管理', to: '/administrator/categories' },
  { label: '标签管理', to: '/administrator/tags' },
]

function handleLogout() {
  clearAuthTokens()
  navigateTo('/administrator/login')
}

const sidebarOpen = ref(false)
const route = useRoute()

// 客户端确认存在 token 后再渲染后台外壳：SSR/首帧不渲染，避免硬刷新时先闪出后台 UI
// （真正的跳转由 middleware/auth.global.ts 完成）
const authed = ref(false)
onMounted(() => {
  authed.value = !!localStorage.getItem('access_token')
})

watch(
  () => route.fullPath,
  () => {
    sidebarOpen.value = false
  },
)
</script>

<template>
  <div v-if="authed" class="flex min-h-screen bg-paper-light text-ink-light dark:bg-stone-900 dark:text-stone-100">
    <header class="fixed inset-x-0 top-0 z-30 flex items-center gap-3 border-b border-stone-200 bg-paper-light/90 px-4 py-3 backdrop-blur dark:border-stone-800 dark:bg-stone-900/90 md:hidden">
      <button
        type="button"
        class="flex h-9 w-9 items-center justify-center rounded-lg border border-stone-300 text-stone-600 dark:border-stone-700 dark:text-stone-300"
        aria-label="打开菜单"
        @click="sidebarOpen = true"
      >
        <Icon name="lucide:menu" class="h-5 w-5" />
      </button>
      <span class="text-lg font-serif font-bold text-brand-600 dark:text-amber-500">{{ site.name }} · 管理</span>
      <ThemeToggle :hoverable="false" class="ml-auto" />
    </header>

    <div v-if="sidebarOpen" class="fixed inset-0 z-30 bg-black/40 md:hidden" @click="sidebarOpen = false" />

    <aside
      class="fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r border-stone-200 bg-stone-100 transition-transform duration-200 dark:border-stone-800 dark:bg-stone-950 md:translate-x-0"
      :class="sidebarOpen ? 'translate-x-0' : '-translate-x-full'"
    >
      <div class="px-6 py-5 text-xl font-serif font-bold text-brand-600 dark:text-amber-500">{{ site.name }} · 管理</div>
      <nav class="flex-1 space-y-1 px-3 py-2">
        <NuxtLink
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          class="flex items-center rounded-lg px-4 py-2.5 text-sm text-stone-700 transition-colors hover:bg-stone-200 hover:text-brand-700 dark:text-stone-300 dark:hover:bg-stone-800 dark:hover:text-amber-400"
        >
          {{ item.label }}
        </NuxtLink>
      </nav>
      <div class="border-t border-stone-200 p-3 dark:border-stone-800">
        <button
          type="button"
          class="w-full rounded-lg px-4 py-2.5 text-sm text-red-600 transition-colors hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/50"
          @click="handleLogout"
        >
          退出登录
        </button>
      </div>
    </aside>

    <main class="flex-1 px-4 pb-6 pt-20 sm:px-6 md:ml-64 md:px-8 md:py-6">
      <header class="mb-6 flex items-center justify-between gap-3 border-b border-stone-200 pb-4 dark:border-stone-800">
        <div class="min-w-0 flex-1"><slot name="title" /></div>
        <div class="hidden md:block"><ThemeToggle /></div>
      </header>
      <slot />
    </main>
  </div>
</template>
