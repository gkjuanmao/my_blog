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
  css: ['~/assets/css/tailwind.css'],
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
