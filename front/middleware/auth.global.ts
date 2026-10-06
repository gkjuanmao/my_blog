/**
 * 后台鉴权中间件（全局）。
 *
 * `/administrator/**`（除登录页）必须携带 access_token，否则跳转登录页。
 * token 存在 localStorage，SSR 读不到，因此只在客户端判定；配合 admin 外壳在
 * 挂载前不渲染（见 layouts/admin.vue），硬刷新时也不会先闪出后台 UI。
 */
export default defineNuxtRouteMiddleware((to) => {
  if (import.meta.server) return
  if (!to.path.startsWith('/administrator')) return
  if (to.path === '/administrator/login') return
  if (!localStorage.getItem('access_token')) {
    return navigateTo('/administrator/login')
  }
})