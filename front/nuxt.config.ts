export default defineNuxtConfig({
  compatibilityDate: '2026-01-01',
  devtools: { enabled: true },
  modules: [
    '@nuxtjs/tailwindcss',
    '@nuxtjs/color-mode',
    '@element-plus/nuxt',
    '@nuxt/icon',
    '@pinia/nuxt',
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
  ],
  nitro: {
    devProxy: {
      '/api/': { target: 'http://127.0.0.1:8000/api', changeOrigin: false },
      '/media/': { target: 'http://127.0.0.1:8000/media', changeOrigin: false },
    },
  },
  devServer: {
    host: '0.0.0.0',
    port: 5173,
  },
})
