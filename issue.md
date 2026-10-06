# my_blog 问题清单（issue.md）

> 生成日期：2026-10-06 · 来源：全仓深度分析（静态审阅 + 实测质量门禁）
> 实测基线：`ruff check` ✅ / `mypy config articles common users` ✅ / `pytest` **336 passed** ✅ / `manage.py check` 1 警告（staticfiles.W004）
>
> 级别图例：**P0** 阻断性缺陷 · **P1** 高优先（功能/安全矛盾） · **P2** 中优先（质量/稳定性） · **P3** 低优先（整洁度/细节）
> 用法：修复一条勾一条；每条含证据（文件:行）与修复建议。行号基于 2026-10-06 的 master（`2aa2bf3`）。

## 修正说明（2026-10-06 核验后）

- **原基线有 3 处需修正**：①「`ruff check` ✅」在核验时为假——未跟踪的 `shrink_images.py` 触发 1 个 E501；②「`pytest` 336 passed ✅」在 Windows 上实为 335 passed + 1 failed（归档 zip 的 Content-Type 平台差异）；③ `TEST-03` 的前提（`.coverage` 陈旧产物）当前不可复现——`.coverage` 与 `tests/reports/` 均不在磁盘/版本库。①②已在 `a7e15a2` 修正，现基线为真。
- **定级修正**：`FE-01`、`TEST-01` 由 **P0 降为 P1**（按本文件图例 P0=阻断性缺陷，二者均不阻断功能、不丢数据）。修正后本清单 **P0 = 0 条**。
- `TEST-03` 的前提已随 `TEST-02` 消失（`.coverage` 已 gitignore 且不存在，`tests/reports/` 已移出版本库）。
- **进度以本文件复选框为准**（已勾选 = 已修复且通过回归：ruff + mypy + pytest）。

## 汇总

| 类别 | 数量 | P0 | P1 | P2 | P3 |
|---|---|---|---|---|---|
| [BE 后端](#be-后端) | 13 | 0 | 2 | 3 | 8 |
| [FE 前端](#fe-前端) | 24 | 1 | 2 | 9 | 12 |
| [TEST 测试与门禁](#test-测试与门禁) | 12 | 1 | 2 | 7 | 2 |
| [OPS 运维部署](#ops-运维部署) | 8 | 0 | 3 | 3 | 2 |
| [DOC 文档漂移](#doc-文档漂移) | 7 | 0 | 2 | 4 | 1 |
| **合计** | **64** | **2** | **11** | **26** | **25** |

建议修复顺序：① TEST-01 + DOC-01~02（低成本堵住"坏代码直达远端"与 AI 误导）→ ② FE-01/FE-02（鉴权链路）→ ③ BE-01（权限统一）→ ④ 其余按级别。

---

## BE 后端

- [x] **BE-01 · P1** 文章/分类/标签 CRUD 只用 `jwt_auth`，与 `staff_auth` 权限模型自相矛盾 —— 导出/导入/传图/HTML 导入要求 staff，而**破坏性更强**的创建/更新/删除/批量删除只要普通登录即可（`articles/api.py:370,498,569,680,690` 及 `:700-812` 的分类标签 CRUD）。缓解因素：无注册接口，用户只能 admin 创建。**建议**：CRUD 全部改 `staff_auth`（或明确文档化"任何登录用户皆可管理"的单一口径），并补权限矩阵测试。
- [x] **BE-02 · P1（采取文档化路径：明确 SQLite 并发上限/备份/恢复，PostgreSQL 保持 opt-in）** 生产是 SQLite + gunicorn `3 workers × 4 threads` 并发写，归档导入持锁期间有写放大/`database is locked` 风险；PostgreSQL 仍是注释 TODO（`config/settings/prod.py:66-77`、`Dockerfile` CMD、`config/settings/base.py:72-78`）。**建议**：要么启用 prod PostgreSQL（compose 加 db 服务），要么明确文档化 SQLite 的并发上限与备份策略。
- [x] **BE-03 · P2** 公开读接口零缓存 —— `/articles/`、`/categories/`、`/tags/` 每次全量查询 + `count()`（`articles/api.py:180-235`），nginx 对 `/api/` 未加任何 `Cache-Control`（`docker/nginx/nginx.conf:145` 附近）。**建议**：短 TTL 缓存（应用层 `cache` 或 nginx `proxy_cache`）+ 公开 GET 加 `Cache-Control: public, max-age=60`。
- [x] **BE-04 · P2** 搜索仅 `title__icontains`（`articles/api.py:230`），正文 Markdown 已入库却不可搜；SQLite `LIKE` 无法利用索引，标题大时全表扫。**建议**：至少把 `summary`/`content` 纳入，或引入 FTS5/简单倒排；同时给 keyword 加长度下限防滥用。
- [x] **BE-05 · P2** 阅读量每次请求无条件 +1（`articles/api.py:248` 的 `F('views')+1`），刷新即计数，无 IP/时间窗去重。`F()` 用法本身正确。**建议**：缓存做"每 IP 每文章 N 小时计一次"的去重键。
- [x] **BE-06 · P3** `manage.py check` 报 `staticfiles.W004`：`STATICFILES_DIRS` 指向不存在的 `static/`（`config/settings/base.py:111`）。**建议**：目录不存在时从设置中剔除，或建空目录并入库（注意 gitignore 不要误伤）。
- [x] **BE-07 · P3** `ArticlesConfig.ready()` 启动即查库触发 Django 6 RuntimeWarning（`articles/apps.py:27` 调 `ensure_defaults()`，本次实测输出）。已有 `DatabaseError` 兜底但告警仍在。**建议**：挪到 `post_migrate` 信号或首次实际访问时惰性创建。
- [x] **BE-08 · P3** 异常信封 `message` 字段类型不一致：`handle_validation_error` 会返回 `message_dict`/`messages`（dict/list），其余分支是 str（`common/exceptions.py:25,27,29`）。前端一律按字符串 `e.data.message` 展开，遇到 dict 会显示 `[object Object]`。**建议**：统一拍平成单行字符串（或前端做类型分支）。
- [x] **BE-09 · P3** 外键用 `prefetch_related` 而非 `select_related`：`_published_articles()` 中 `prefetch_related('tags', 'category')`（`articles/api.py:182`，另 `:267` 同样写法）——FK 走 prefetch 会多发一条查询。**建议**：`select_related('category')` + `prefetch_related('tags')`。
- [x] **BE-10 · P3** `cover_image_sha256`/`file_sha256` 的 `verbose_name` 仍写"**源文件** SHA-256"（`articles/models.py:75,83`），而实际语义（AGENTS.md 与归档实现）是"**当前落盘文件**的字节哈希"——语义文档与字段名矛盾，易误导后续开发按源字节比对（AGENTS.md 明确警告过这是实测教训）。**建议**：改 verbose_name/字段注释与实现对齐。
- [x] **BE-11 · P3** Swagger UI `/api/v1/docs` 在生产公开可访问（`config/urls.py:16` 的 `NinjaAPI` 无 `docs_url` 环境开关，nginx `/api/` 直通）。**建议**：`DEBUG` 或显式环境变量才开 docs。
- [x] **BE-12 · P3** 死代码：`common/pagination.py`（`CustomPagination`，django-ninja 1.6 后已不可用且列表改为手动分页）、`common/utils.py`（空文件）。**建议**：删除或注明保留原因。
- [x] **BE-13 · P3** JWT 认证每请求同步查库 `User.objects.get(pk=...)`（`users/authentication.py:21`），高并发下多一次 DB 往返。**建议**：短期缓存用户（注意停用/删号失效），或接受现状并注释。

---

## FE 前端

- [x] **FE-01 · P0→P1** **refresh_token 写入后全项目从未被读取**：`login.vue:16-17` 写入 `localStorage`，`useApi.ts:59,118` 与 `layouts/admin.vue:10` 只清 `access_token`；access 生命周期仅 2h（`config/settings/base.py:85`）→ 后台每 2 小时被踢回登录页，后端整套 refresh 轮换 + 黑名单机制形同虚设；401 时 `refresh_token` 残留。**建议**：实现 401 → `POST /token/refresh/` 重试队列（利用后端已有的轮换+黑名单），成功后写回新对，失败清空两个 token。
- [x] **FE-02 · P1** 无路由中间件（`front/middleware/` 不存在）：未登录直接访问 `/administrator/*` 会先渲染后台外壳，等首个 API 401 才被重定向（闪后台 UI）。**建议**：加 `middleware/auth.ts`，client 侧检查 token 存在性 + `definePageMeta` 挂到所有后台页。
- [x] **FE-03 · P1** **零 SEO**：全仓 `useHead` 仅用于挂皮肤类（`front/layouts/default.vue:13`），文章页无 `title`/`description`/Open Graph/结构化数据——对博客是流量硬伤。**建议**：`useSeoMeta` 按文章 title/summary/cover 填充，列表页/分类页补默认 title 与 `titleTemplate`。
- [x] **FE-04 · P2（已加 nginx 基础 CSP；httpOnly cookie 仍列为中期项）** 安全组合风险：JWT 存 `localStorage`（`useApi.ts:41`）+ 多处 `v-html`（`article/[slug].vue:56`、`ArticleForm.vue:293`）+ 无 CSP 头（nginx 未加 `Content-Security-Policy`）——安全性完全外包给后端 nh3 消毒。**建议**：nginx 加基础 CSP；中期考虑 httpOnly cookie 或至少 `Authorization` 内存化。
- [x] **FE-05 · P2** 错误提示口径不一致：公开页取 `e?.message`（ofetch 技术串如 `[GET] .../ 500`，`pages/index.vue:22`、`search.vue:32`、`tags.vue:12`、`categories.vue:12`、`category/[slug].vue:31`、`tag/[slug].vue:31`），后台取 `e?.data?.message`。**建议**：`useApi` 统一抛出后端中文 `message`，公开页兜底文案本地化。
- [x] **FE-06 · P2（用 useRequestGuard 序号守卫替代 signal 透传：无需处理 AbortError）** 列表请求无竞态守卫（无 AbortController/请求序号）：公开列表 `pages/index.vue:10-29`、后台 `pages/administrator/articles/index.vue:38-59,477` 快速翻页时旧响应可能覆盖新数据。**建议**：`useApi` 加 signal 透传 + 单调序号丢弃过期响应。
- [x] **FE-07 · P2** `pages/administrator/articles/edit/[id].vue:7` 的 `const id = Number(route.params.id)` 只在 setup 计算一次，同路由换 id 不重取（`article/[slug].vue:5-7` 已用 computed 规避此坑，编辑页没有）。**建议**：改 `computed(() => Number(route.params.id))` 并 `watch` 重拉。
- [x] **FE-08 · P2（改纯文本，列表用「；」连接，彻底去掉 dangerouslyUseHTMLString）** `ElMessage` 用 `dangerouslyUseHTMLString` 注入服务端拼接串（`blocking_reasons.join('<br>')`、报告字段，`pages/administrator/articles/index.vue:162-165,232-243`）。当前来源可信 + 仅 staff 可见，但后端文案一旦含用户可控内容即成存储型 XSS。**建议**：改 `v-html` 插槽白名单渲染或纯文本 + `\n`。
- [ ] **FE-09 · P2** `pages/administrator/articles/index.vue` **822 行单文件**（全项目最大），桌面表格（`:574` 起）与移动卡片（`:614` 起）模板整段重复，且内含导入三阶段流程。**建议**：拆 `components/admin/`（列表表格、移动卡片、ImportDialog、ExportBar），目标单文件 <300 行。
- [ ] **FE-10 · P2** `pages/administrator/categories.vue`（130 行）与 `tags.vue`（125 行）结构 1:1 雷同（fetchList/openCreate/openEdit/handleSave/handleDelete + 双视图）。**建议**：抽 `useCrudTable` composable 或泛型 CRUD 组件。
- [ ] **FE-11 · P2** 4 个公开列表页复制同一套 `articles/loading/errorMsg + grid + AppPagination` 模板（`index.vue:44-54`、`category/[slug].vue:52-62`、`tag/[slug].vue` 同构、`search.vue:94-105`）。**建议**：抽 `ArticleListSection` 组件 + `useArticleList` composable。
- [x] **FE-12 · P2（49→9 处 any：新增 `ApiError` + `errorMessage()`，catch/ref/上传回调全部收紧；剩余 9 处是 el-table 作用域插槽标注，el-table 插槽类型为 DefaultRow，无法收窄）** 48 处 `any`（`catch (e: any)`、`ref<any>`、`uploadWithProgress(options: any)`（`articles/index.vue:352`）、`file: any` 等），TS 声明完整但类型质量打折。**建议**：定义 `ApiError` 类型（`{status?, data?: {message?}}`）替换 catch 里的 any，逐步收紧。
- [x] **FE-13 · P2（vue-tsc 纳入 `check` 默认路径，新增 `--no-front` 跳过；无 front 依赖时 warn 降级）** 默认质量门禁**不含 `vue-tsc`**：`scripts/blog.sh:511-519` 需显式 `--front` 才跑，类型回归可静默进主干。**建议**：纳入 `check` 默认路径（或 CI），至少在提交约定里强制。
- [ ] **FE-14 · P2（部分完成：已加 vitest + 5 个纯逻辑用例，并纳入 `blog.sh check` 与 CI；ESLint 部分待补——现有代码无 lint 基线，直接引入 recommended 会让新门禁立即失败，需单独一轮清理）** 前端无 ESLint/Prettier 配置、无任何测试框架（`front/package.json` 仅 build/dev/preview/postinstall）。**建议**：加 `@nuxt/eslint-config` 最小规则集 + vitest 覆盖 `useApi`/`usePageQuery` 等纯逻辑。
- [x] **FE-15 · P3** Pinia 死依赖：`nuxt.config.ts:9` 注册 `@pinia/nuxt` 但全仓零 `defineStore`。**建议**：移除依赖与模块注册（或落地真用）。
- [x] **FE-16 · P3** 无 `error.vue`：SSR 期错误走 Nuxt 默认 500 页，与中文站/皮肤风格脱节。**建议**：自定义 `error.vue` 中文化 + 返回首页/重试按钮。
- [x] **FE-17 · P3** 后台列表分页用裸 `ref`（`pages/administrator/articles/index.vue:27-28`），未接 `usePageQuery` → 刷新丢页码，与公开页"分页写 URL、后退可回"（`f621d16`）的既定特性不一致。**建议**：后台列表也走 `usePageQuery`。
- [x] **FE-18 · P3（新增 `front/constants/uploads.ts` 单一来源 + `formatMB()`，提示语不再硬编码 MB 数字）** 上传上限/尺寸文案散落 7 处硬编码（`ArticleForm.vue:49-50,91,242,286,332,360,371`：20MB/50MB/10MB/60MB/1920/100MB），与后端 `covers.py`/`images.py`/`nginx.conf` 阈值靠人肉同步。**建议**：后端出一个 `GET /admin/limits/`（已有 `import/limits/` 可扩展）或前端单一 `constants/uploads.ts`。
- [x] **FE-19 · P3（新增 `app.config.ts` 的 `site.name/tagline` 单一来源；nuxt.config 的静态 head 默认值需手工同步，已在文件内注明）** 品牌名「旅行游记」硬编码于 `layouts/default.vue:50,121`、`layouts/admin.vue:35,44`、`login.vue:32`、`index.vue:38` 等多处。**建议**：收敛到 `app.config.ts`。
- [x] **FE-20 · P3（改用 `data-skin` 语义锚点，JS 选择器与两套皮肤 CSS 同步替换，元素集合与旧选择器一致）** `useSkinMotion.ts:12-14` 用 Tailwind 类名（`article.group`、`a.rounded-2xl`、`a.bg-brand-600`）当动效选择器锚点——改一个工具类动效就静默失效。**建议**：改语义 `data-*` 属性锚点。
- [x] **FE-21 · P3（两个 rAF 循环改为「离屏 / 后台标签页暂停」，hero 画布加 IntersectionObserver；MutationObserver 仅在有新增节点时重扫）** 皮肤动效在非默认皮肤下常驻 2 个 rAF 循环（粒子 + 光晕）+ 全子树 `MutationObserver`（`useSkinMotion.ts:143-278,281-321,333-337`），低端设备滚动掉帧风险；已做 reduced-motion/`pointer:fine` 降级但无 FPS/长任务保护。**建议**：离屏暂停 rAF、Observer 只观察新增节点。
- [ ] **FE-22 · P3** SSR 公开页在 setup 顶层 `await` 且回源要再经一跳 nginx（`useApi.ts:48`），后端慢则整页白屏，无超时/降级。**建议**：`useAsyncData` 加 `lazy` 或超时 + 骨架屏。
- [ ] **FE-23 · P3** 日期格式化三处各写各的：`components/ArticleCard.vue:6-11`、`pages/article/[slug].vue:11-16`、`articles/index.vue:602,634`（后者直接 `toLocaleString`）。**建议**：抽 `utils/date.ts` 统一格式与 `Asia/Shanghai` 口径。
- [ ] **FE-24 · P3** 亮/暗切换按钮在 `layouts/default.vue` 写了两遍（`:63-75` 桌面 vs `:80-91` 移动，仅 class 细微差异）。**建议**：抽子组件传入 class 差异。

---

## TEST 测试与门禁

- [x] **TEST-01 · P0→P1** **完全无 CI**：无 `.github/`、`.gitea/`、`.forgejo/`、pre-commit、git hook（`.git/hooks` 仅默认 sample），唯一门禁是手动 `scripts/blog.sh check`；而仓库约定"提交后直接 push"，坏代码可直达远端。**建议**：最小 Gitea webhook/act runner 或本地 pre-push hook 跑 `blog.sh check`。
- [x] **TEST-02 · P1** **陈旧报告入 git**：`tests/reports/junit.xml` + `TEST_REPORT.md`（git 追踪中）停在 2026-09-30、141 用例/88%，实况 **336** 用例，落后 195 个。**建议**：从版本库移除改为门禁产物，或在 `check` 中自动刷新后强制提交。
- [x] **TEST-03 · P1（随 TEST-02 解决）** `.coverage` 同为 2026-09-30 陈旧产物且**行号已错位**（记录 `articles/api.py` 最大 506 行，实际 1111 行），现在跑 `coverage report` 读出的 45% 是假象；`htmlcov/` 已被清理但 TEST_REPORT.md 仍引用。**建议**：重跑一次 `pytest --cov` 生成真数据，或停止在文档里引用固定覆盖率。
- [ ] **TEST-04 · P2** `config/` 完全零覆盖：`prod.py`（TLS 开关、ALLOWED_HOSTS 回落、Redis/LocMem 分支、缺 SECRET_KEY 的 RuntimeError）、`config/urls.py` 路由顺序（仅归档导出有回归）、`wsgi/asgi`——测试恒走 `config.settings.dev`（`pyproject.toml` 直指）。**建议**：补 prod 配置单测（`override_settings`/monkeypatch env）。
- [ ] **TEST-05 · P2** `purge_archives` 管理命令零测试，而 `entrypoint.sh` 每次启动与 `blog.sh purge` 都会执行它（`recompress_covers`/`purge_inline_images` 都有 command 级测试，唯独它没有）。**建议**：补 dry-run/`--delete`/边界（过期未消费 staging）用例。
- [ ] **TEST-06 · P2** `common/exceptions` 的 500 兜底分支无测试（TEST_REPORT 自标 70%），`common/pagination.py` 长期 0%（未引用，与 BE-12 同源）。**建议**：补 500 信封断言（含"不泄露内部信息"这条设计意图）。
- [ ] **TEST-07 · P2** `blog.sh`（802 行）仅 `bash -n` 语法检查，未接 **shellcheck**（脚本内已有 `# shellcheck disable` 注释说明本地用过，但门禁没跑）。**建议**：`check` 加 `shellcheck scripts/blog.sh`。
- [ ] **TEST-08 · P2** `check` 中的 `nginx -t` 依赖本地已有 `nginx:1.27` 镜像，缺失时**静默降级为 warn 不阻断**（`scripts/blog.sh` check 段）。**建议**：区分"可选增强"与"必检项"，或缺镜像时拉取。
- [ ] **TEST-09 · P2** 无端到端/冒烟自动化：唯一运行时检查是 `blog.sh up` 时的 3 条 `HEALTH_PATHS` 轮询，nginx→gunicorn→SQLite 真实链路无自动化覆盖。**建议**：`check --e2e` 起容器后跑登录+建文章+导出冒烟。
- [ ] **TEST-10 · P2** prod 启动路径未测：`check_env_file` 的 prod 分支（缺 `DJANGO_SECRET_KEY` 报错）、`DJANGO_USE_TLS=true` 下 `SECURE_PROXY_SSL_HEADER`、`.env.example` 自动生成逻辑。**建议**：shell 级 bats/手工脚本用例或最小化 Python 测试。
- [ ] **TEST-11 · P3** `scripts/seed_demo.py`（约 24KB 生成器）无任何测试。**建议**：至少测其产物可被 `import stage/commit` 接受（`blog.sh seed-demo` 已走真实链路，可抽成断言）。
- [ ] **TEST-12 · P3** 并发/多 worker 行为未测：LocMemCache 下导入锁 fail-open 退化场景、nginx `limit_conn 2` 与 Django 锁配合、`views` 并发 `F()` 更新。**建议**：文档化已知限制即可（P2 级修复见 BE-02）。

---

## OPS 运维部署

- [ ] **OPS-01 · P1** `docker-compose.yml` 服务全部**无 `restart:` 策略** —— 容器崩溃或宿主重启后不会自愈。**建议**：app/front/nginx/redis 统一 `restart: unless-stopped`。
- [ ] **OPS-02 · P1** **无 healthcheck**：compose 无 `healthcheck:`、Dockerfile 无 `HEALTHCHECK` 指令 —— 绕开 `blog.sh` 直接 `docker compose up` 时无就绪判定，nginx 会在 app 未起时 502。**建议**：app 加 `curl /api/v1/articles/` 探活，nginx `depends_on: condition: service_healthy`。
- [ ] **OPS-03 · P1** nginx 对 **`/admin/`（Django admin 登录页）与 `/api/v1/login/` 无 `limit_req`**：现有 zone 只覆盖 archive(1r/s) 与 preview(5r/s)（`docker/nginx/nginx.conf:5,9`）；API 层只有应用内缓存限流，admin session 登录完全无限流。**建议**：新增 `limit_req_zone` 覆盖这两个 location（如 5r/s burst=10）。
- [ ] **OPS-04 · P2** `.env.example` 中 `REDIS_URL` 处于**注释状态**，而 prod 无 Redis 时会回落 LocMemCache 并触发 RuntimeWarning（`prod.py:51-73`）—— 手工 `DJANGO_ENV=prod` 本地跑极易漏配，导致导入锁/登录限流在 3 worker 下各自为政。**建议**：`.env.example` 默认启用该行并加醒目注释（compose 已注入，风险主要在手工路径）。
- [ ] **OPS-05 · P2** 纯 HTTP + nginx 端口绑 `0.0.0.0`（`docker-compose.yml` `18888:18888`），`DJANGO_USE_TLS` 默认关 —— 内网取舍可接受，但 TLS 启用路径（`DJANGO_USE_TLS` + `SECURE_PROXY_SSL_HEADER` + HSTS）从未实测验证。**建议**：至少做一次 TLS 演练并把步骤写入 `docs/`。
- [ ] **OPS-06 · P2** `media/`（64 文件/1.9MB，不入 git）数据迁移只靠 `blog.sh seed-media`，`import` 结尾仅一行 hint，易被忽略 → 新机器导入文章后封面 404。**建议**：`import` 结束时检测 media 卷为空并显式警告/自动执行 seed-media。
- [x] **OPS-07 · P3** `scripts/blog.sh` 头部注释（L7-19）的子命令清单**漏列 `seed-media`**（`usage()` 与 `main()` 分发里都有）。**建议**：补齐注释。
- [ ] **OPS-08 · P3** 无数据库备份/恢复机制：SQLite 单文件靠 `db_data/` bind mount，`blog.sh` 无 `backup` 子命令，`down --purge`/误删 `db_data` 即全站数据丢失。**建议**：加 `blog.sh backup`（`sqlite3 .backup` 或复制 + 校验）并文档化恢复步骤。

---

## DOC 文档漂移

- [x] **DOC-01 · P1** `AGENTS.md:16` 称"共 **281** 个用例"，实测 **336**（AI 主要上下文，漂移会直接误导后续开发）。**建议**：改为动态表述（"以 `pytest --collect-only` 为准"）或更新数字。
- [x] **DOC-02 · P1** `AGENTS.md:80` 称"`docker-compose.yml` 仅含 app+nginx（redis 已移除）"，实况是 **4 服务（app/redis/nginx/front）**且 app 已注入 `REDIS_URL`；`prod.py:51` 注释"当前 docker-compose 未含 redis"同样过时——两处都还会引导读者"去配置已有东西"。**建议**：同步改写。
- [x] **DOC-03 · P2** `AGENTS.md` 称"`templates/` 和 `static/` 存在但为空"，实况**两目录都不存在**（并触发 staticfiles.W004，见 BE-06）。**建议**：改描述 + 修 W004。
- [x] **DOC-04 · P2** `TEST.md`（1023 行，2026-09-29）**实质失效**：仍写 `rest_framework_simplejwt`（实为 `ninja_jwt`）、旧"返回数组"断言，完全未覆盖归档导入导出/Markdown 正文/内联图/HTML 导入 4 大特性与近 200 个用例；其定位是"供 AI 生成测试的规范"，会产出过期代码。**建议**：顶部加显著"已过期，以 `tests/` 为准"横幅，或重写为索引式文档。
- [x] **DOC-05 · P2** `front/README.md` 仍是 Nuxt 官方 starter 模板，与项目无关。**建议**：替换为前端实际开发/构建说明（或删除指向根 README）。
- [x] **DOC-06 · P2（随 TEST-02 解决）** `tests/reports/` 入 git 且陈旧（见 TEST-02/03）——文档与产物双重漂移。**建议**：与 TEST-02 一并处理。
- [ ] **DOC-07 · P3** 文档体系整体缺少"漂移自查"机制：`DESIGN.md`（SSOT）自 9 月底后经历归档 v2/WebP/HTML 导入等大改，未逐条核验是否同步（本次仅抽查发现上述各处）。**建议**：`blog.sh check` 增加轻量文档断言（如从 `pytest --collect-only` 提取用例数与 AGENTS.md 声明比对）。

---

## 附：验证命令（修复后回归用）

```bash
uv run ruff check .                      # Lint
uv run mypy config articles common users # 类型
uv run pytest -q                         # 336 用例（数字随修复变化需同步 DOC-01）
uv run python manage.py check            # 应无 staticfiles.W004（BE-06）
bash -n scripts/blog.sh && shellcheck scripts/blog.sh   # TEST-07 修复后
scripts/blog.sh check                    # 默认含 vue-tsc（FE-13 已纳入默认门禁；--no-front 跳过）
```
