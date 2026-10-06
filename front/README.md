# 个人博客前端（Nuxt 3）

本目录是博客的前端应用，通过 `/api/v1/` 调用同仓的 Django 后端。整体部署方式见仓库根目录的 `AGENTS.md` 与 `DESIGN.md`（设计 SSOT）。

## 技术栈

- Nuxt 3（Vue 3 + TypeScript，SSR）
- Tailwind CSS + Element Plus（`@element-plus/nuxt`，中文 locale）
- `@nuxtjs/color-mode`（亮/暗模式）、`@nuxt/icon`（构建期内联 lucide 图标，离线可用）

## 目录速览

- `pages/` — 前台页面（首页/搜索/分类/标签/文章详情）+ `pages/administrator/` 后台（登录、文章、分类、标签）
- `layouts/` — `default`（前台外壳）与 `admin`（后台外壳）
- `components/` — 公共组件，`components/admin/` 为后台专用
- `composables/` — `useApi`（统一请求与鉴权）、`usePageQuery`（分页写 URL）、`useSkinMotion` 等
- `types/api.ts` — 后端响应类型声明

## 本地开发

前端需配合后端一起跑。先启动后端（默认 `http://127.0.0.1:8000`）：

```bash
# 仓库根目录
uv run python manage.py runserver 0.0.0.0:8000
```

再启动前端 dev server（默认 `http://localhost:5173`）：

```bash
npm install
npm run dev
```

`nuxt.config.ts` 的 `nitro.devProxy` 已把 `/api/`、`/media/` 反代到 `127.0.0.1:8000`，无需额外配置 CORS。

## 类型检查

提交前请运行（`blog.sh check` 默认也会跑，需先装好 front 依赖）：

```bash
node node_modules/vue-tsc/bin/vue-tsc.js --noEmit
```

## 构建与部署

```bash
npm run build     # 产出 .output（自包含，无需 node_modules）
```

生产由 `front/Dockerfile` 多阶段构建，容器内以 `.output` 运行；对外仅经 nginx（`:18888`）访问，前端运行时通过 `NUXT_PUBLIC_API_BASE=/api/v1/` 调用后端。完整部署/离线镜像流程见 `docs/OFFLINE_IMAGE_DEPLOY.md`。