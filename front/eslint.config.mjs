// 前端 ESLint 扁平配置（FE-14）。
//
// 用 @nuxt/eslint-config 的 Nuxt 预设（Vue + TypeScript 基础规则），但**关掉**两类噪音源：
//   - stylistic：代码风格/格式化。本项目未引入 Prettier，逐条对齐风格会产生成百上千条
//     与 bug 无关的告警，把有效信号淹没；
//   - formatters：对 md/json 等非 JS 文件的格式化。
// 门禁只关心「可能出错的写法」，故保留预设里的正确性规则（no-unused-vars、vue 基础规则、
// typescript 的 no-floating-promises 类检查等）。
//
// 忽略项沿用 `.gitignore`（预设内置 flat-gitignore），故 .nuxt/.output/node_modules 自动跳过。
import { createConfigForNuxt } from '@nuxt/eslint-config/flat'

export default createConfigForNuxt({
  features: {
    stylistic: false,
    formatters: false,
    tooling: false,
  },
}).append({
  rules: {
    // Nuxt 约定用单词文件名（index.vue / error.vue / admin.vue…），该规则不适用
    'vue/multi-word-component-names': 'off',
  },
})