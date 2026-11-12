<script setup lang="ts">
import type { Skin } from '~/composables/useAppTheme'

const { site } = useAppConfig()
const { skin, skinClass, isSkinActive, setSkin } = useAppTheme()
const route = useRoute()
const colorMode = useColorMode()

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

/** 首页全出血 + 卷首版式；其他页保持原容器宽度与内距 */
const isHome = computed(() => route.path === '/')

/** 时间轴与首页共用「卷首式」导航（fixed 透明浮层 + 滚动状态机 + 进度条）；
 *  时间轴顶态是浅色画布而非深色照片，顶态配色由 home-cover.css 的 .tl-page 段单独覆盖 */
const isTimeline = computed(() => route.path === '/timeline')
const useCoverNav = computed(() => isHome.value || isTimeline.value)

const navLinks: { label: string; to: string; browse?: 'category' | 'tag' | 'search' }[] = [
  { label: '首页', to: '/' },
  { label: '时间轴', to: '/timeline' },
  { label: '分类', to: '/categories', browse: 'category' },
  { label: '标签', to: '/tags', browse: 'tag' },
  { label: '搜索', to: '/search', browse: 'search' },
]

/* 浏览弹窗（搜索/分类/标签）：三项导航走弹窗，其余仍走路由 */
const browseOpen = ref(false)
const browseMode = ref<'category' | 'tag' | 'search'>('search')

function onNavClick(
  link: { to: string; browse?: 'category' | 'tag' | 'search' },
  event: Event,
) {
  // 统一接管点击：browse 项开弹窗（绝不跳转），其余走客户端路由
  event.preventDefault()
  event.stopPropagation()
  if (link.browse) {
    if (sheetOpen.value) closeMenu()
    browseMode.value = link.browse
    browseOpen.value = true
    return
  }
  if (sheetOpen.value) closeMenu()
  if (route.path !== link.to) void navigateTo(link.to)
}

const skinOptions: { value: Skin; label: string }[] = [
  { value: 'default', label: '默认风格' },
  { value: 'elegant', label: '优雅（暖色）' },
  { value: 'neon', label: '赛博（霓虹）' },
]

const isDark = computed(() => colorMode.value === 'dark')

/* -------------------------------------------------------------------------
 * 首页/时间轴导航状态机 + 进度条 + 视差：**全页唯一**的 scroll 监听（passive + rAF 节流）
 * 滚动回调里只写 CSS 变量与 navState，不读 layout（缓存 scrollHeight，resize 时重算）
 * ---------------------------------------------------------------------- */
const navState = ref<'top' | 'scrolled'>('top')
let stopScroll: (() => void) | null = null

function setupHomeScroll() {
  teardownHomeScroll()
  if (!import.meta.client || !useCoverNav.value) return

  const root = document.documentElement
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)')
  let maxScroll = 0
  let frame = 0
  let ticking = false

  const measure = () => {
    maxScroll = Math.max(0, root.scrollHeight - window.innerHeight)
  }

  const write = () => {
    ticking = false
    const y = window.scrollY
    // 回退阈值 32 / 前进阈值 40：滞后 8px，避免在临界点抖动
    if (y > 40) navState.value = 'scrolled'
    else if (y < 32) navState.value = 'top'
    if (reduced.matches) return
    root.style.setProperty(
      '--hp-progress',
      maxScroll > 0 ? Math.min(1, y / maxScroll).toFixed(4) : '0',
    )
    // 视差上限 60px（照片上下各留 60px 余量）；移动端强制 0，避免与地址栏收缩叠加
    root.style.setProperty(
      '--hp-parallax-y',
      `${window.innerWidth < 768 ? 0 : Math.min(60, y * 0.1).toFixed(1)}px`,
    )
  }

  const onScroll = () => {
    if (ticking) return
    ticking = true
    frame = requestAnimationFrame(write)
  }

  window.addEventListener('scroll', onScroll, { passive: true })
  window.addEventListener('resize', measure, { passive: true })
  // 内容高度会随数据/字体变化：用 ResizeObserver 更新缓存，避免在滚动回调里读 scrollHeight
  const ro = new ResizeObserver(measure)
  ro.observe(document.body)

  measure()
  write()

  stopScroll = () => {
    window.removeEventListener('scroll', onScroll)
    window.removeEventListener('resize', measure)
    cancelAnimationFrame(frame)
    ro.disconnect()
    root.style.removeProperty('--hp-progress')
    root.style.removeProperty('--hp-parallax-y')
  }
}

function teardownHomeScroll() {
  stopScroll?.()
  stopScroll = null
  navState.value = 'top'
}

onMounted(setupHomeScroll)
onBeforeUnmount(teardownHomeScroll)
watch(useCoverNav, async () => {
  teardownHomeScroll()
  await nextTick()
  setupHomeScroll()
})

/* -------------------------------------------------------------------------
 * 移动端抽屉：原生 <dialog> + showModal()
 * 免费拿到焦点陷阱 / Esc 关闭 / 背景 inert。
 * ⚠️ dialog 在 top layer，Element Plus 的 popper 挂到 body 的普通层级 → 抽屉里
 *    不能出现任何 EP 弹出层组件（皮肤选择用原生 radio，亮暗用原生 button）。
 * ---------------------------------------------------------------------- */
const sheetEl = ref<HTMLDialogElement | null>(null)
const menuBtn = ref<HTMLButtonElement | null>(null)
const sheetOpen = ref(false)
let wideQuery: MediaQueryList | null = null

function lockBackground(locked: boolean) {
  document.documentElement.style.overflow = locked ? 'hidden' : ''
}

function syncClosed() {
  sheetOpen.value = false
  lockBackground(false)
  // 关闭（Esc / 关闭按钮 / 点背板 / 点链接）后焦点必须回到触发按钮
  menuBtn.value?.focus()
}

function openMenu() {
  const dlg = sheetEl.value
  if (!dlg || dlg.open) return
  sheetOpen.value = true
  if (typeof dlg.showModal === 'function') dlg.showModal()
  // 特征检测失败时的降级：仍然打开并手动聚焦（Esc 靠下面的 keydown 兜底）
  else dlg.setAttribute('open', '')
  lockBackground(true)
  void nextTick(() => {
    // 焦点进第一个链接（不是关闭按钮：用户的目的是导航）
    dlg.querySelector<HTMLElement>('.cv-sheet__nav a')?.focus()
  })
}

function closeMenu() {
  const dlg = sheetEl.value
  if (!dlg || !dlg.open) {
    syncClosed()
    return
  }
  if (typeof dlg.close === 'function') {
    // close() 会触发原生 close 事件 → syncClosed
    dlg.close()
  } else {
    dlg.removeAttribute('open')
    syncClosed()
  }
}

function onSheetClick(event: MouseEvent) {
  // 点背板关闭：只有背板被点时才把 target 指向 dialog 自身
  if (event.target === sheetEl.value) closeMenu()
}

function onWideChange(event: MediaQueryListEvent) {
  // 尺寸跨到 ≥768 必须关掉，否则抽屉悬空、菜单按钮不可见 → 用户被困。
  // 抽屉没开时什么都不做：closeMenu 会把焦点抢到菜单按钮上。
  if (event.matches && sheetOpen.value) closeMenu()
}

function toggleDark() {
  if (isSkinActive.value) return
  colorMode.preference = isDark.value ? 'light' : 'dark'
}

watch(
  () => route.fullPath,
  () => {
    if (sheetOpen.value) closeMenu()
  },
)

onMounted(() => {
  wideQuery = window.matchMedia('(min-width: 768px)')
  wideQuery.addEventListener('change', onWideChange)
})

onBeforeUnmount(() => {
  wideQuery?.removeEventListener('change', onWideChange)
  wideQuery = null
  lockBackground(false)
})
</script>

<template>
  <div class="public-shell flex min-h-screen flex-col bg-paper-light text-ink-light dark:bg-stone-900 dark:text-stone-100">
    <a class="skip-link" href="#main">跳到主要内容</a>

    <header
      :class="useCoverNav
        ? 'cv-nav cv-nav--home'
        : 'sticky top-0 z-10 border-b border-stone-200 bg-paper-light/80 backdrop-blur dark:border-stone-800 dark:bg-stone-900/80'"
      :data-nav="useCoverNav ? navState : undefined"
    >
      <span v-if="useCoverNav" class="cv-nav__veil" aria-hidden="true"/>
      <div v-if="useCoverNav" class="cv-progress" aria-hidden="true">
        <span class="cv-progress__bar"/>
      </div>

      <div :class="useCoverNav ? 'cv-nav__inner' : 'mx-auto flex max-w-5xl items-center justify-between px-4 py-3 sm:px-6 sm:py-4'">
        <NuxtLink
          to="/"
          :class="useCoverNav
            ? 'cv-nav__brand'
            : 'text-xl font-serif font-bold tracking-wide text-brand-600 dark:text-amber-500 sm:text-2xl'"
        >
          {{ site.name }}
        </NuxtLink>

        <!-- 首页/时间轴：链接居中，桌面才出现 -->
        <nav v-if="useCoverNav" class="cv-nav__links" aria-label="主导航">
          <a
            v-for="link in navLinks"
            :key="link.to"
            :href="link.to"
            class="cv-nav__link"
            :aria-current="route.path === link.to ? 'page' : undefined"
            @click="onNavClick(link, $event)"
          >
            {{ link.label }}
          </a>
        </nav>

        <div v-if="useCoverNav" class="cv-nav__actions">
          <SkinSwitcher />
          <ThemeToggle />
        </div>

        <!-- 其他页：保持原有「链接 + 图标同一行、整体右对齐」的布局 -->
        <div v-else class="hidden items-center gap-6 md:flex">
          <nav class="flex items-center gap-6" aria-label="主导航">
            <a
              v-for="link in navLinks"
              :key="link.to"
              :href="link.to"
              class="text-sm text-stone-600 transition-colors hover:text-brand-600 dark:text-stone-300 dark:hover:text-amber-400"
              :aria-current="route.path === link.to ? 'page' : undefined"
              @click="onNavClick(link, $event)"
            >
              {{ link.label }}
            </a>
          </nav>
          <SkinSwitcher />
          <ThemeToggle />
        </div>

        <!-- <768：顶栏只留菜单按钮（皮肤与亮暗进抽屉，带中文标签） -->
        <div class="flex items-center gap-2 md:hidden">
          <button
            ref="menuBtn"
            type="button"
            :class="useCoverNav
              ? 'cv-menu-btn'
              : 'flex h-9 w-9 items-center justify-center rounded-full border border-stone-300 text-stone-600 dark:border-stone-700 dark:text-stone-300'"
            :aria-expanded="sheetOpen"
            aria-controls="cv-mobile-menu"
            :aria-label="sheetOpen ? '关闭菜单' : '打开菜单'"
            @click="openMenu"
          >
            <Icon :name="sheetOpen ? 'lucide:x' : 'lucide:menu'" class="h-5 w-5" />
          </button>
        </div>
      </div>
    </header>

    <main
      id="main"
      tabindex="-1"
      :class="useCoverNav
        ? 'w-full flex-1'
        : 'mx-auto w-full max-w-5xl flex-1 px-4 py-6 sm:px-6 sm:py-8'"
    >
      <slot />
    </main>

    <footer class="cv-footer">
      <div class="cv-footer__inner">
        <div>
          <p class="cv-footer__brand">{{ site.name }}</p>
          <p class="cv-footer__tagline">{{ site.tagline }}</p>
        </div>
        <div class="cv-footer__right">
          <p class="cv-footer__copy">© 2026 {{ site.name }} · 文艺 · 极简</p>
          <p class="cv-footer__hint">可在右上角切换外观与减少动效</p>
        </div>
      </div>
    </footer>

    <!-- 移动端菜单：顶部下滑面板。内容不得包含任何 EP 弹出层组件（top layer 会盖住 popper） -->
    <dialog
      id="cv-mobile-menu"
      ref="sheetEl"
      class="cv-sheet"
      aria-label="站点菜单"
      @close="syncClosed"
      @click="onSheetClick"
    >
      <div class="cv-sheet__head">
        <span class="cv-sheet__title">{{ site.name }}</span>
        <button type="button" class="cv-sheet__close" aria-label="关闭菜单" @click="closeMenu">
          <Icon name="lucide:x" class="h-5 w-5" />
        </button>
      </div>

      <nav class="cv-sheet__nav" aria-label="移动端导航">
        <ul role="list">
          <li v-for="link in navLinks" :key="link.to">
            <a
              :href="link.to"
              :aria-current="route.path === link.to ? 'page' : undefined"
              @click="onNavClick(link, $event)"
            >
              {{ link.label }}
            </a>
          </li>
        </ul>
      </nav>

      <fieldset class="cv-sheet__group">
        <legend>界面风格</legend>
        <label v-for="option in skinOptions" :key="option.value" class="cv-sheet__radio">
          <input
            type="radio"
            name="cv-skin"
            :value="option.value"
            :checked="skin === option.value"
            @change="setSkin(option.value)"
          >
          <span>{{ option.label }}</span>
        </label>
        <p class="cv-sheet__hint">
          {{ isSkinActive ? '当前风格自带明暗，切回「默认风格」可调整亮/暗' : '风格会改变整站配色，默认风格支持亮/暗切换' }}
        </p>
      </fieldset>

      <fieldset class="cv-sheet__group">
        <legend>亮 / 暗</legend>
        <button
          type="button"
          class="cv-sheet__switch"
          role="switch"
          :aria-checked="isDark"
          :disabled="isSkinActive"
          @click="toggleDark"
        >
          <span>深色模式</span>
          <span class="cv-sheet__switch-state">{{ isDark ? '已开启' : '已关闭' }}</span>
        </button>
      </fieldset>
    </dialog>

    <BrowseDialog v-model:open="browseOpen" :initial-mode="browseMode" />
  </div>
</template>
