/**
 * 公开页的「皮肤」切换：默认 / 优雅 / 赛博霓虹。
 *
 * - 皮肤用 cookie 持久化，SSR 即可读到并渲染正确皮肤，避免首屏闪烁
 * - 皮肤与「亮/暗」互斥：皮肤自带明暗基调，选中皮肤时强制亮色（避免浅底 + 暗色组件冲突）
 * - 皮肤类只挂在公开页布局上（见 layouts/default.vue），后台 admin 布局不受影响
 */
export type Skin = 'default' | 'elegant' | 'neon'

/** 皮肤对应的 <html> 类名（default 无类） */
const SKIN_CLASS: Record<Skin, string> = {
  default: '',
  elegant: 'skin-elegant',
  neon: 'skin-neon',
}

export function useAppTheme() {
  const skinCookie = useCookie<Skin>('blog_skin', {
    default: () => 'default',
    maxAge: 60 * 60 * 24 * 365,
    sameSite: 'lax',
  })
  const colorMode = useColorMode()
  const route = useRoute()

  // 后台路由（含 /administrator/login —— 它沿用公开布局）一律不套皮肤
  const isAdminRoute = computed(() => route.path.startsWith('/administrator'))

  const preference = computed<Skin>(() =>
    skinCookie.value === 'elegant' || skinCookie.value === 'neon' ? skinCookie.value : 'default',
  )

  /** 实际生效的皮肤：后台路由强制回落默认 */
  const skin = computed<Skin>(() => (isAdminRoute.value ? 'default' : preference.value))

  /** 是否处于非默认皮肤（此时亮/暗切换应禁用） */
  const isSkinActive = computed(() => skin.value !== 'default')

  /** 主题选择器是否可见（后台隐藏） */
  const switcherVisible = computed(() => !isAdminRoute.value)

  /** 要挂到 <html> 上的皮肤类名（响应式，供 useHead 使用） */
  const skinClass = computed(() => SKIN_CLASS[skin.value])

  function setSkin(next: Skin) {
    skinCookie.value = next
    if (next !== 'default') {
      // 皮肤自带明暗基调，统一按亮色渲染；否则浅底皮肤叠加 dark 组件会不可读
      colorMode.preference = 'light'
    }
  }

  return { skin, skinClass, isSkinActive, switcherVisible, setSkin }
}