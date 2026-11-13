<script setup lang="ts">
/**
 * 管理台外壳：编辑部台账（见 assets/css/admin-desk.css）。
 *
 * 与首页同源但不复用首页叙事：墨青侧栏 + 纸张内容区 + 顶栏面包屑；
 * ≤1024px 侧栏收为抽屉。
 *
 * 后台恒为浅色纸面（.ad-desk 内重新声明 --hp-* 亮色值），因此不提供主题切换；
 * 想跟随后台暗色时改 admin-desk.css 第 1 节的令牌即可。
 */
import type { UserInfo } from '~/types/api'

const { site } = useAppConfig()
const route = useRoute()

/** 当前登录者：用于顶部显示真实账号名，并决定「用户管理」是否出现在导航里 */
const me = ref<{ username: string, is_staff: boolean, is_superuser: boolean } | null>(null)

const baseNavItems = [
  { label: '总览', to: '/administrator/dashboard' },
  { label: '文章', to: '/administrator/articles' },
  { label: '分类', to: '/administrator/categories' },
  { label: '标签', to: '/administrator/tags' },
]

// 用户管理只对超管开放（后端 /admin/users/** 同样只放超管），
// 非超管看不到入口，避免点进去只收获一个 403。
const navItems = computed(() =>
  me.value?.is_superuser
    ? [...baseNavItems, { label: '用户', to: '/administrator/users' }]
    : baseNavItems,
)

const roleText = computed(() => {
  if (!me.value) return '管理'
  if (me.value.is_superuser) return '超级管理员'
  return me.value.is_staff ? '编辑' : '作者'
})

/** 文章详情/编辑也归属「文章」 */
function isActive(to: string): boolean {
  if (to === '/administrator/articles') return route.path.startsWith('/administrator/articles')
  return route.path === to
}

const currentLabel = computed(() => {
  if (route.path.startsWith('/administrator/articles')) return '文章'
  return navItems.value.find(item => item.to === route.path)?.label ?? '管理'
})

const today = computed(() => {
  const now = new Date()
  const week = ['日', '一', '二', '三', '四', '五', '六'][now.getDay()]
  return `${now.getFullYear()}年${now.getMonth() + 1}月${now.getDate()}日 · 周${week}`
})

const sealChar = computed(() => site.name.trim().charAt(0) || '编')

function handleLogout() {
  clearAuthTokens()
  navigateTo('/administrator/login')
}

const sidebarOpen = ref(false)
const authed = ref(false)

// 客户端确认存在 token 后再渲染后台外壳：SSR/首帧不渲染，避免硬刷新时先闪出后台 UI
// （真正的跳转由 middleware/auth.global.ts 完成）
onMounted(async () => {
  authed.value = !!localStorage.getItem('access_token')
  if (!authed.value) return
  try {
    const { data } = await useApi().get<UserInfo>('/me/')
    me.value = data
  } catch {
    // 401 已由 useApi 统一清 token 并跳登录页，这里不再重复处理
  }
})

watch(
  () => route.fullPath,
  () => {
    sidebarOpen.value = false
  },
)

// 弹窗/消息会被 teleport 到 body，靠 body 上的类名把皮肤带到 body 级元素
useHead({
  title: () => `${currentLabel.value} · 管理`,
  bodyAttrs: { class: 'ad-body' },
})
</script>

<template>
  <div v-if="authed" class="ad-desk">
    <a class="ad-skip" href="#ad-stage">跳到主要内容</a>

    <div class="ad-shell">
      <aside class="ad-rail" :class="{ 'is-open': sidebarOpen }">
        <div class="ad-rail__head">
          <NuxtLink class="ad-rail__brand" to="/">{{ site.name }}
            <span class="ad-rail__kicker">编辑部 · Editor's Desk</span>
          </NuxtLink>
        </div>

        <nav class="ad-rail__nav" aria-label="管理导航">
          <NuxtLink
            v-for="item in navItems"
            :key="item.to"
            class="ad-rail__link"
            :to="item.to"
            :aria-current="isActive(item.to) ? 'page' : undefined"
          >
            {{ item.label }}
          </NuxtLink>
        </nav>

        <div class="ad-rail__foot">
          <a class="ad-rail__site" href="/" target="_blank" rel="noopener">
            查看站点 <span aria-hidden="true">↗</span>
          </a>
          <div class="ad-rail__user">
            <span class="ad-seal ad-seal--rail" aria-hidden="true">{{ sealChar }}</span>
            <span class="ad-rail__user-name">{{ me?.username ?? '…' }}<em>{{ roleText }}</em></span>
          </div>
          <button class="ad-rail__logout" type="button" @click="handleLogout">退出登录</button>
        </div>
      </aside>

      <button
        v-if="sidebarOpen"
        class="ad-rail__scrim"
        type="button"
        aria-label="关闭菜单"
        @click="sidebarOpen = false"
      />

      <div class="ad-main">
        <header class="ad-topbar">
          <button
            class="ad-topbar__menu"
            type="button"
            aria-label="打开菜单"
            :aria-expanded="sidebarOpen"
            @click="sidebarOpen = true"
          >
            <svg width="16" height="12" viewBox="0 0 16 12" fill="none" aria-hidden="true">
              <path d="M0 1h16M0 6h16M0 11h16" stroke="currentColor" stroke-width="1.4" />
            </svg>
          </button>
          <p class="ad-topbar__crumb">
            <span>管理台</span><span class="sep" aria-hidden="true">/</span>
            <strong>{{ currentLabel }}</strong>
          </p>
          <div class="ad-topbar__right">
            <span class="ad-topbar__date">{{ today }}</span>
            <span class="ad-topbar__sep" aria-hidden="true" />
            <a class="ad-topbar__link" href="/" target="_blank" rel="noopener">前台首页 ↗</a>
          </div>
        </header>

        <main id="ad-stage" class="ad-stage" tabindex="-1">
          <slot />
        </main>
      </div>
    </div>
  </div>
</template>
