/**
 * 站点级配置（品牌名/标语）：UI 文案与 SEO 的单一来源。
 * 注意 `nuxt.config.ts` 的 `app.head` 是构建期静态默认值，无法读取本文件，
 * 修改品牌名时请一并同步（`title` / `og:site_name` / `description`）。
 */
export default defineAppConfig({
  site: {
    name: '旅行游记',
    tagline: '记录山川湖海，也收藏人间烟火。',
  },
})