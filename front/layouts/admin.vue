<script setup lang="ts">
/**
 * 管理台外壳：编辑部工作台（见 assets/css/admin-desk.css）。
 *
 * 版式：墨青书脊（可收成 72px 图标条）+ 顶栏（面包屑 / 全局搜索 / 前台入口）+
 * 全幅内容区。内容区是 `height:100%` 的 flex 列，各页自己滚、页脚恒在窗口底部，
 * 所以不会再出现「页脚被推到屏幕外」的情况。
 *
 * 与首页同源但不复用首页叙事：后台恒为浅色纸面（.ad-desk 内重新声明 --hp-* 亮色值），
 * 因此不提供主题切换；想跟随后台暗色时改 admin-desk.css 第 1 节的令牌即可。
 */
import type { AdminIconName } from '~/types/admin'
import type { UserInfo } from '~/types/api'

const { site } = useAppConfig()
const route = useRoute()

/** 当前登录者：用于顶部显示真实账号名，并决定「用户管理」是否出现在导航里 */
const me = ref<Pick<UserInfo, 'username' | 'is_staff' | 'is_superuser'> | null>(null)

type NavItem = { label: string; to: string; icon: AdminIconName }

//: staff（编辑）专属：分类与标签是**全站结构**，作者只能决定自己稿件挂哪个栏目，
//: 不能新建/改名栏目——否则多人导入后分类树会被各人的命名塞满。
const editorNavItems: NavItem[] = [
  { label: '分类', to: '/administrator/categories', icon: 'folder' },
  { label: '标签', to: '/administrator/tags', icon: 'hash' },
]

// 有导入任务在跑时，导航上挂一个计数，避免用户不知道后台还在干活
const { activeCount } = useImportTasks()

// 导航按角色分组：所有登录用户都能写/导自己的稿；分类标签给编辑；用户管理给超管。
// 前端只做「不展示注定 403 的入口」，真正的门在服务端。
const navGroups = computed<Array<{ label: string; items: NavItem[] }>>(() => {
  const groups: Array<{ label: string; items: NavItem[] }> = [
    {
      label: '编务',
      items: [
        { label: '总览', to: '/administrator/dashboard', icon: 'grid' },
        { label: '文章', to: '/administrator/articles', icon: 'doc' },
      ],
    },
  ]
  if (me.value?.is_staff) groups.push({ label: '结构', items: editorNavItems })
  groups.push({
    label: '系统',
    items: [
      { label: '任务', to: '/administrator/tasks', icon: 'clock' },
      ...(me.value?.is_superuser
        ? [{ label: '用户', to: '/administrator/users', icon: 'users' as AdminIconName }]
        : []),
    ],
  })
  return groups
})

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
  for (const group of navGroups.value) {
    const hit = group.items.find(item => item.to === route.path)
    if (hit) return hit.label
  }
  return '管理'
})

const today = computed(() => {
  const now = new Date()
  const week = ['日', '一', '二', '三', '四', '五', '六'][now.getDay()]
  return `${now.getFullYear()}年${now.getMonth() + 1}月${now.getDate()}日 · 周${week}`
})

const sealChar = computed(() => site.name.trim().charAt(0) || '编')
const meChar = computed(() => (me.value?.username ?? '管').trim().charAt(0) || '管')

function handleLogout() {
  clearAuthTokens()
  navigateTo('/administrator/login')
}

/** 书脊收起：只留图标，正文吃满宽度 */
const isMini = ref(false)

/** 顶栏全局搜索：跳到「文章」页并按关键词过滤（后端没有跨资源搜索接口） */
const searchText = ref('')
const searchInput = ref<HTMLInputElement | null>(null)

function submitSearch() {
  const keyword = searchText.value.trim()
  navigateTo({ path: '/administrator/articles', query: keyword ? { keyword } : {} })
}

function onShortcut(event: KeyboardEvent) {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    searchInput.value?.focus()
  }
}

/** 窄屏默认收起 */
function syncRail() {
  isMini.value = window.innerWidth < 1160
}

const authed = ref(false)
/** 改密弹窗：放在外壳里而不是某个页面，这样任何后台页面都能改，且改完不影响当前页面状态 */
const passwordOpen = ref(false)

// 客户端确认存在 token 后再渲染后台外壳：SSR/首帧不渲染，避免硬刷新时先闪出后台 UI
// （真正的跳转由 middleware/auth.global.ts 完成）
onMounted(async () => {
  authed.value = !!localStorage.getItem('access_token')
  if (!authed.value) return
  syncRail()
  window.addEventListener('resize', syncRail)
  window.addEventListener('keydown', onShortcut)
  try {
    const { data } = await useApi().get<UserInfo>('/me/')
    me.value = data
  } catch {
    // 401 已由 useApi 统一清 token 并跳登录页，这里不再重复处理
  }
})

onUnmounted(() => {
  window.removeEventListener('resize', syncRail)
  window.removeEventListener('keydown', onShortcut)
})

// 弹窗/消息会被 teleport 到 body，靠 body 上的类名把皮肤带到 body 级元素
useHead({
  title: () => `${currentLabel.value} · 管理`,
  bodyAttrs: { class: 'ad-body' },
})
</script>

<template>
  <div v-if="authed" class="ad-desk" :class="{ 'is-mini': isMini }">
    <a class="ad-skip" href="#ad-stage">跳到主要内容</a>

    <aside class="ad-rail">
      <div class="ad-rail__head">
        <NuxtLink class="ad-rail__brand" to="/" :title="site.name">
          <span class="ad-rail__seal" aria-hidden="true">{{ sealChar }}</span>
          <span class="ad-rail__brand-text">
            <span class="ad-rail__name">{{ site.name }}</span>
            <span class="ad-rail__kicker">EDITOR'S DESK</span>
          </span>
        </NuxtLink>
      </div>

      <nav class="ad-nav" aria-label="管理导航">
        <template v-for="group in navGroups" :key="group.label">
          <p class="ad-nav__group">{{ group.label }}</p>
          <NuxtLink
            v-for="item in group.items"
            :key="item.to"
            class="ad-nav__link"
            :to="item.to"
            :title="item.label"
            :aria-current="isActive(item.to) ? 'page' : undefined"
          >
            <AdminIcon class="ad-nav__icon" :name="item.icon" />
            <span class="ad-nav__label">{{ item.label }}</span>
            <span
              v-if="item.to === '/administrator/tasks' && activeCount"
              class="ad-rail__badge"
              :aria-label="`${activeCount} 个导入任务进行中`"
              >{{ activeCount }}</span
            >
          </NuxtLink>
        </template>
      </nav>

      <div class="ad-rail__foot">
        <a class="ad-rail__site" href="/" target="_blank" rel="noopener" title="查看站点">
          <span class="ad-rail__site-text">查看站点</span>
          <AdminIcon name="ext" :size="13" />
        </a>
        <div class="ad-rail__user">
          <span class="ad-rail__avatar" aria-hidden="true">{{ meChar }}</span>
          <span class="ad-rail__user-meta">
            <span class="ad-rail__uname">{{ me?.username ?? '…' }}</span>
            <span class="ad-rail__urole">{{ roleText }}</span>
          </span>
        </div>
        <div class="ad-rail__acts">
          <button class="ad-rail__act" type="button" title="修改密码" @click="passwordOpen = true">
            <AdminIcon name="key" />
            <span>改密</span>
          </button>
          <button class="ad-rail__act" type="button" title="退出登录" @click="handleLogout">
            <AdminIcon name="out" />
            <span>退出</span>
          </button>
        </div>
      </div>
    </aside>

    <div class="ad-main">
      <header class="ad-topbar">
        <button
          class="ad-topbar__toggle"
          type="button"
          :aria-label="isMini ? '展开侧栏' : '收起侧栏'"
          :aria-expanded="!isMini"
          @click="isMini = !isMini"
        >
          <AdminIcon name="menu" />
        </button>

        <p class="ad-crumb">
          <span>管理台</span>
          <span aria-hidden="true">/</span>
          <b>{{ currentLabel }}</b>
        </p>

        <form class="ad-search" role="search" @submit.prevent="submitSearch">
          <AdminIcon name="search" :size="14" />
          <input
            ref="searchInput"
            v-model="searchText"
            type="search"
            placeholder="搜索文章标题或 slug…"
            aria-label="搜索文章"
          >
          <kbd>⌘K</kbd>
        </form>

        <span class="ad-topbar__date">{{ today }}</span>
        <span class="ad-topbar__sep" aria-hidden="true" />
        <a class="ad-topbar__link" href="/" target="_blank" rel="noopener">前台首页 ↗</a>
        <span class="ad-topbar__me" aria-hidden="true">{{ meChar }}</span>
      </header>

      <main id="ad-stage" class="ad-stage" tabindex="-1">
        <slot />
      </main>
    </div>

    <ChangePasswordDialog v-model="passwordOpen" />

    <!-- 导入任务通知器：放外壳里，关掉导入弹窗或切页也能收到「任务完成」 -->
    <ImportTaskWatcher />
  </div>
</template>
