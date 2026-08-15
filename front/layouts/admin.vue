<script setup lang="ts">
const navItems = [
  { label: '仪表盘', to: '/admin' },
  { label: '文章管理', to: '/admin/articles' },
  { label: '分类管理', to: '/admin/categories' },
  { label: '标签管理', to: '/admin/tags' },
]

function handleLogout() {
  if (import.meta.client) localStorage.removeItem('access_token')
  navigateTo('/admin/login')
}
</script>

<template>
  <div class="flex min-h-screen bg-paper-light text-ink-light dark:bg-stone-900 dark:text-stone-100">
    <aside class="fixed inset-y-0 left-0 z-20 flex w-64 flex-col border-r border-stone-200 bg-stone-100 dark:border-stone-800 dark:bg-stone-950">
      <div class="px-6 py-5 text-xl font-serif font-bold text-brand-600 dark:text-amber-500">旅行游记 · 管理</div>
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

    <main class="ml-64 flex-1 px-8 py-6">
      <header class="mb-6 border-b border-stone-200 pb-4 dark:border-stone-800">
        <slot name="title" />
      </header>
      <slot />
    </main>
  </div>
</template>
