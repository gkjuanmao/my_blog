/**
 * 开发代理目标（nitro.devProxy 的 /api/ 与 /media/ 前缀指向哪里）。
 * 默认指向本机后端；需要连局域网 / 远程后端时用
 * `NUXT_DEV_PROXY_TARGET=http://192.168.x.x:port npm run dev` 覆盖，不要把内网地址写进仓库。
 */
const DEV_PROXY_TARGET = process.env.NUXT_DEV_PROXY_TARGET || 'http://127.0.0.1:8000'

export default defineNuxtConfig({
  compatibilityDate: '2026-01-01',
  devtools: { enabled: true },
  // 站点级 SEO 默认值（页面只需 useSeoMeta({ title }) 提供页面名；
  // 标题模板在 app.vue 用函数形式设置：站点名不重复拼接）
  app: {
    head: {
      title: '旅行游记',
      htmlAttrs: { lang: 'zh-CN' },
      meta: [
        { name: 'description', content: '记录山川湖海，也收藏人间烟火。' },
        { property: 'og:site_name', content: '旅行游记' },
      ],
    },
  },
  modules: [
    '@nuxtjs/tailwindcss',
    '@nuxtjs/color-mode',
    '@element-plus/nuxt',
    '@nuxt/icon',
  ],
  components: [{ path: '~/components', pathPrefix: false }],
  // 图标改为构建期打包进产物。@nuxt/icon 默认在运行时向 api.iconify.design 取图标，
  // 离线/局域网部署取不到时图标会消失（实测：主题切换按钮点一次后变成空圈）。
  // 配合 @iconify-json/lucide 与 clientBundle.scan，图标数据随 bundle 一起发布，不再依赖外网。
  icon: {
    serverBundle: { collections: ['lucide'] },
    clientBundle: { scan: true },
  },
  runtimeConfig: {
    public: {
      apiBase: '/api/v1/',
    },
  },
  elementPlus: {
    themes: ['dark'],
    defaultLocale: 'zh-cn',
  },
  colorMode: {
    classSuffix: '',
    preference: 'system',
    fallback: 'light',
  },
  css: [
    '~/assets/css/tailwind.css',
    // 皮肤样式必须排在 tailwind 之后，才能在同等优先级下覆盖工具类
    '~/assets/css/skin-elegant.css',
    '~/assets/css/skin-neon.css',
    // 首页卷首视觉层：必须排在两套皮肤之后（等权重时靠文件顺序胜出）
    '~/assets/css/home-cover.css',
  ],
  nitro: {
    devProxy: {
      '/api/': { target: `${DEV_PROXY_TARGET}/api`, changeOrigin: false },
      '/media/': { target: `${DEV_PROXY_TARGET}/media`, changeOrigin: false },
    },
  },
  devServer: {
    host: '0.0.0.0',
    port: 5173,
  },
})
