/**
 * 当前登录者（模块级单例）。
 *
 * 为什么要抽：`layouts/admin.vue` 已经拉过一次 `/me/`，但页面拿不到它的结果，
 * 于是「按权限显隐某个按钮」的页面各拉一次——既浪费请求，也会出现两处判断不一致。
 * 这里做一次请求、全局复用；`ensureMe()` 幂等，多页面并发调用只会发一次。
 */
import type { UserInfo } from '~/types/api'

const me = ref<UserInfo | null>(null)
let inFlight: Promise<UserInfo | null> | null = null
let loaded = false

async function ensureMe(): Promise<UserInfo | null> {
  if (loaded) return me.value
  if (inFlight) return inFlight
  inFlight = (async () => {
    try {
      const { data } = await useApi().get<UserInfo>('/me/')
      me.value = data
      loaded = true
      return data
    } catch {
      // 401 已由 useApi 统一清 token 并跳登录页，这里只保证不重复请求
      return null
    } finally {
      inFlight = null
    }
  })()
  return inFlight
}

/** 仅用于测试/切换账号后复位 */
export function resetMe(): void {
  me.value = null
  loaded = false
  inFlight = null
}

export function useMe() {
  const isSuperuser = computed(() => Boolean(me.value?.is_superuser))
  const isStaff = computed(() => Boolean(me.value?.is_staff))
  return { me, isSuperuser, isStaff, ensureMe }
}
