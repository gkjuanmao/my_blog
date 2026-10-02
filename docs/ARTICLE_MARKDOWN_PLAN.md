# 文章详情页改造：PDF 附件展示 → Markdown 正文（含压缩插图）— 方案 v1.0（定稿）

> 目标读者：实现者 / 评审者。本文为**修改方案**，不含实现代码。
> 项目：Django 6 + django-ninja 后端，Nuxt 3 前端，nginx + podman/docker 部署。
> 核心诉求：详情页以 Markdown 呈现正文并插入图片；在**完整展示**前提下尽可能压缩**内网穿透流量**。
> 评审历史（9 轮、11 名独立 agent 交叉评审）：v0.1 → 一轮 24 条 → v0.2 → 二轮 13 条 → v0.3 → 三轮 12 条 → v0.4 → 四轮 13 条 → v0.5 → 五轮 9 条 → v0.6 → 六轮 8 条 → v0.7 → 七轮 9 条 → v0.8 → 八轮 3 条 → v0.9 → 九轮 1 条 → **v1.0（本文，无阻断/高，定稿）**。

## 0. 已确认的产品取舍（用户 2026-10-02 拍板）

- **A1 附件改为可选**；**A2 存量回退**（正文为空 → 只给附件下载入口，移除 PDF 预览）；**A3 图片转 WebP、剥离 EXIF、最长边 ≤1920，单尺寸**；**A4 封面仍必填**；**A5 正文与附件至少填一项**（create / update / 归档导入三条路径，按**最终状态**校验）。

## 0.1 v0.5 → v0.6 修订（对应第五轮评审）

| 来源 | 修订 |
|---|---|
| 攻击#1（**高**） | `key: () => 'article-'+slug` + `watch:[slug]` **无效**：`slug = route.params.slug as string` 是常量（`[slug].vue:5`），同路由仅参数变化时 setup 不重跑 → 必须改 **`const slug = computed(() => route.params.slug as string)`** |
| 攻击#2（中） | 幂等键含 `sha256(content)` 但 DB **无 content 哈希列**，`_identical_article` 纯 DB filter 无法过滤 → 改为**按 slug 取候选后在 Python 比对**（v1 无 content 键则跳过） |
| 攻击#3（中） | 「至少一项」放进 `validate_package` 会**误拒合法的 update**（stage 不查库、不知目标既有正文/附件）→ **intrinsic 上限（200k 字符 / ≤50 图）留在 validate；「至少一项」下沉到 planner**（它能拿到目标文章） |
| 攻击#4（中） | `ARTICLES_PER_EXPORT` 未删净（`limits.py:80` 仍是 blocker，`api.py:943`、`front/types/api.ts:160` 仍下发）→ 改为**保留该门禁并与 entries 对齐**（1000 篇 × 2 成员 = 2000 entries，两者同点触发，无矛盾），仅删除 `count*3` 算术 |
| 攻击#5（中） | purge 回收站：目标目录未 `mkdir` 会 `FileNotFoundError`；且 `inline/_trash/` 仍在 nginx `/media/` 暴露面内（被 immutable 缓存直出，比 404 更糟）→ 回收站移到 **`MEDIA_ROOT/_inline_trash/`** 并加 **nginx `location ^~ /media/_inline_trash/ { return 404; }`**，写前 `mkdir` |
| 攻击#6（中） | `store_inline_image` 纳入 `written` 补偿会**误删其他文章在用的同内容图**（内容寻址同名）→ **inline 不纳入补偿**，孤儿统一交 purge |
| 攻击#7（低） | nh3 默认 `link_rel` 会与 treeprocessor 注入的 `rel` 打架 → 显式 `link_rel=None`，`rel` 由我们注入，并测试钉住 |
| 审计#9（假闭合） | §0.1 曾称「复用方会刷新 mtime」——**复用分支是 `exists → return`，根本不 touch mtime**，该保护不存在。删除该说法；误删保护只依赖回收站 + 归还窗口 |
| 审计#4 | importer 重读字节后**必须与 validate 记录的 `stored_sha256` 比对**（一致才继续） |
| 审计#11（**唯一遗留高**） | nh3 是否保留**相对 `src`** 与 `loading/decoding/target/rel` 未实测 → 改为**不依赖 nh3 保属性**：nh3 只做白名单消毒，`loading/decoding/target/rel` 在消毒后由**服务端 HTML 解析器**按严格规则回填（只对 `img[src]`/`a[href]` 且 src/href 通过本地或 http(s) 校验的节点）；相对 URL 保留行为以 **P1 spike 测试**为准，不通过则走计划 B（见 §5.1） |

## 0.2 v0.6 → v0.7 修订（对应第六轮评审）

| 来源 | 修订 |
|---|---|
| 攻击#1 / 审计#8（**阻断/高**） | **`stored_sha256` 语义错位**：它是「重编码后落盘字节」哈希，而 importer 重读的是 zip 内**原始字节**，仅在已规范化时才相等 → 任何需重编码的封面/图都会恒不等而误判失败。明确 **importer 重读原始字节后必须先重跑 `process_cover()` / `process_inline_image()`**，用其**产物**哈希与 `stored_sha256` 比对 |
| 攻击#2（**阻断/高**） | entries 计数漏了包内固定成员 **`manifest.json` + `README.md`**（导入侧 `_check_infos` 按全部文件判 `validate.py:237`）→ 1000 篇实际 2002 > 2000，自产自拒。estimate 改为实际总文件数 **含 +2 固定成员**；`ARTICLES_PER_EXPORT` 与 entries 不再声称"同点触发"，只声明**导出与导入用同一实际总数** |
| 攻击#3（中） | `html.parser` 回填属性会破坏 HTML：默认 `convert_charrefs=True` 会把 nh3 已转义的 `&lt;` 解回 `<`，回写时等于**在消毒后重新引入标签**。约束为 **`convert_charrefs=False`**，只在 `handle_starttag` 追加属性，`handle_data`/`handle_entityref`/`handle_charref` 原样回写 |
| 攻击#4（中） | 计划 B 被低估（自建 sanitizer 有 mXSS 风险）→ 计划 B 改为 **仍用 nh3 做消毒，只自建 URL 策略**（不改用自研 sanitizer）；且氨水默认 `url_relative=PassThrough`，spike 很可能直接通过 |
| 攻击#5（中） | inline 图缺「已规范化即原样」的固定点 → 显式定义 canonical：**WebP + 最长边 ≤1920 + 无 EXIF/ICC** 才原样返回；否则统一 剥 EXIF → 缩放 → 有损重编码，保证「导出→导入→再导出」收敛（防重演封面每轮重写） |
| 攻击#6（低） | 同步点补 `scripts/seed_demo.py:375,424,428`（硬编码 v1 schema）；`ignored_on_import` **无需改动**（content/images 是要导入的） |
| 攻击#7（低） | nh3 白名单补 `code[class]`（fenced_code 的语言类）与 `th[align]`/`td[align]`（表格对齐），否则功能退化 |
| 攻击#8（低） | 回收站落 `MEDIA_ROOT/_inline_trash/` 会被 `cp media/.` 与整目录备份带走（`^~` 只挡访问面）——接受并记录 |

## 0.3 v0.7 → v0.8 修订（对应第七轮评审）

| 来源 | 修订 |
|---|---|
| 攻击#1（**高**） | estimate 只累加 `default_storage.size`（磁盘文件），**漏了「生成型成员」**（`article.json` / `manifest.json` / `README.md` 是现生成的，不在磁盘，`export.py:100-113,165-175`）→ 正文 200k 字符/篇时 JSON 可达数百 MB，导出放过而导入 `budget.charge` 拒绝 = 自产自拒。改为 estimate **对每篇序列化 JSON 后计真实字节**（含 manifest/README），与导入 budget 同口径 |
| 攻击#2（**高**） | 计划 B 的「占位符 ↔ 真实 URL」与属性回填器/提取器的**顺序未钉死** → 若还原晚于回填，`src` 仍是占位符，`loading/decoding` 被丢，且 §7.2 提取器会把占位符当 src → **导出静默漏打包图片**。钉死唯一顺序：**渲染 → nh3 消毒 → 还原真实 URL → 回填属性 →（导出时）提取** |
| 攻击#5（中） | canonical 判定时机歧义：若在 `exif_transpose` 之后判（EXIF 已丢），会把**带方向信息的旋转原图**误判 canonical 并返回**仍含 EXIF 的原始字节**（元数据泄露 + 每轮重写）。明确 canonical 判定在 **transpose 之前、对原始输入**做，「原样返回」= 返回**原始字节** |
| 攻击#6（中） | `store_inline_image` 无条件命名 `.webp`；判定一旦有误，非 WebP 字节会以 `.webp` 落盘，nginx 按扩展名发 `Content-Type: image/webp` + `nosniff` → 解码失败。改为 **store 内断言 `img.format == 'WEBP'`**（或按实际格式定扩展名） |
| 攻击#3（中） | `process_inline_image` 签名不可共用（收 `UploadedFile`，而 importer/validate 只有 zip 字节 + entry 名）。统一核心签名为 **`(data: bytes, ext: str, lim) -> (bytes, warnings)`**（与已有 `process_cover(data, ext, lim)` 同形），端点侧再包 `UploadedFile` |
| 攻击#4（中） | entries 与「单篇 ≤50 图」的容量关系未点明：每篇最少 2 成员、**最多 53 成员**。明确 **`entries` 才是唯一有效约束**（无图时约 999 篇封顶，有图时约 37 篇），`ARTICLES_PER_EXPORT=1000` 恒不先触发、属冗余但无害的粗过滤（保留以免改接口/前端） |
| 攻击#7 / 审计#6（低） | 修正同步点事实：`seed_demo.py:375,424` 用的是 `SCHEMA_ARTICLE/SCHEMA_ARCHIVE` **常量**（改常量即自动跟随）；`seed_demo.py:374-407` 的 article payload 需补 `content` 键；并补 `tests/test_archive_import.py:350`（v1 fixture，bump 后会新增 schema warning，需核对断言） |

## 0.4 v0.8 → v0.9 修订（对应第八轮评审）

| 来源 | 修订 |
|---|---|
| 攻击#（**高·条件**） | 提取器被 `export` / `skip 补齐` / `purge` 三处共用；若它**系统性返回空集**（渲染异常、nh3 行为漂移），purge 会把**全库 inline 图当孤儿批量删除 → 全站正文图 404**。加 **fail-closed 守卫**：`inline/` 目录非空而引用集为空 → **中止并报错**（绝不删除）；并用「DB 原始 `content` 的 `/media/inline/` 字面量扫描」作为交叉校验（与提取器互为佐证） |
| 审计#1 | estimate 的 bytes 是**保守多算**（导入 `budget.charge` 只计 article.json + 媒体，不计 manifest/README），安全；但必须**复用导出同一 `json.dumps(..., ensure_ascii=False, indent=2) + '\n'`**，否则 CJK 被 `\uXXXX` 放大数倍导致合法大正文包被误拒 |
| 审计#4 | 修正算术：「每篇最多 53 成员」（article.json + 封面 + 附件 + 50 图），有图时 `(2000-2)/53 ≈ 37` 篇封顶 |
| 审计#7/#9 | 修正行号引用：`seed_demo.py:428` 实为 manifest 的 `ignored_on_import`（无需改），导出 payload 在 `:374-407` |

## 0.5 v0.9 → v1.0 修订（对应第九轮评审，最后一处）

| 来源 | 修订 |
|---|---|
| 第九轮（**高·自反噬**） | v0.9 的 fail-closed 守卫条件过宽：当**用户清空/删除所有正文**、`inline/` 确实全为孤儿时，提取器与字面量扫描**双空** → 守卫恒命中 → purge **永久拒绝清理**（而它是 inline 唯一 owner，回收路径死锁）。收窄为**只把「提取器为空 **而** 字面量扫描非空」当作真正的提取器失效信号**并中止；**双空视为确实无引用，放行至回收站**（仍经 pass-2 归还，非硬删，安全）。另加显式逃生口 **`--force`**（仍走回收站，不硬删）。补测试：正文全清空后 `--delete` 能正常完成清理 |

## 1. 现状事实（逐条核对源码）

| # | 事实 | 依据 |
|---|---|---|
| F1 | `Article.content` 曾在 `0001_initial` 存在，`0002_remove_article_content` 已删除 | `articles/migrations/0001_initial.py:51`、`0002_...py` |
| F2 | `PdfViewer`（`vue-pdf-embed` + `pdfjs-dist`）仅被 `front/pages/article/[slug].vue` 引用 | grep 全前端仅 1 处 |
| F3 | `Article.file` not null 必填；`create_article` 的 `attachment` 必填 | `articles/models.py:76`、`articles/api.py:372` |
| F4 | 上传接口按扩展名+字节数校验后原样落盘 | `articles/api.py:90-105` |
| F5 | nginx `/media/` 直出 `expires 7d` + `public` + `nosniff`，无鉴权 | `docker/nginx/nginx.conf:33-39` |
| F6 | 普通 `/api/` `client_max_body_size 60m`；归档 1g | `docker/nginx/nginx.conf:13,65-79` |
| F7 | 归档 schema=`myblog.article/v1`；MISSING 哨兵；`tests/test_archive_export.py:116` 钉死 v1 | `articles/archive/format.py:10,74-116` |
| F8 | 上限 `JSON_BYTES=256KB`、entries 500、单文件 50MB、总解压 500MB、`ARTICLES_PER_EXPORT=1000`；`limits.py:62,80,82` | `config/settings/base.py:138-150`、`limits.py` |
| F9 | 列表 `ArticleOut` 不含正文；详情/管理详情用 `ArticleDetailOut` | `articles/schemas.py:172-197` |
| F10 | 管理详情 `GET /admin/articles/{article_id}/` | `articles/api.py:353-364` |
| F11 | 归档路由顺序敏感；ninja 路径首次匹配、方法不符直接 405 不回落 | `articles/api.py:245,328`、`ninja/operation.py:669-695` |
| F12 | 详情页 `slug` 是**常量**；取数用 `ref`+顶层 `await` | `front/pages/article/[slug].vue:5,27-40` |
| F13 | 前端无 markdown 依赖；`front/Dockerfile` 用 `npm ci` | `front/package.json` |
| F14 | `seed-media` 用 `cp media/.` 整目录拷贝 | `scripts/blog.sh:619-633` |
| F15 | `_identical_article` 是纯 DB `filter().first()`，要求 cover+attachment 非 None；导出 `entries=count*3` | `articles/archive/planner.py:96-108`、`export.py:103-113` |
| F16 | `post_delete` 只清理封面/附件文件 | `articles/signals.py:16` |
| F17 | nginx.conf 是 bind mount；`up -d` 不因配置变更重启容器 | `docker-compose.yml:35` |
| F18 | `Storage.save()` 遇同名追加随机后缀；`_save` 用 `O_EXCL` 失败即改名重试 | `django/core/files/storage/filesystem.py:90-134,176` |
| F19 | gunicorn `gthread` 3 worker × 4 threads | `Dockerfile:47-49` |
| F20 | `validate_package` 将媒体字节常驻内存；**不查库**；commit 重新解析原包 | `articles/archive/validate.py:149,487,514-519,664-672`、`articles/api.py:863` |
| F21 | `SCHEMA_ARCHIVE` 硬编码于 `api.py:702`、`importer.py:50`；压缩比按成员判 `validate.py:174` | 源码 |
| F22 | `planner`/`importer` 依赖 `MediaRef.stored_bytes`；补偿 `_delete_files` 在 `importer.py:266` | `planner.py:104,202,206`、`importer.py:135,150,266` |
| F23 | `limits.py:80` 的 `article_count > max_articles_per_export` 仍是 blocker；`api.py:943` 与 `front/types/api.ts:160` 仍下发/展示 | 源码 |
| F24 | Django 6 未配 `STORAGES` → `default_storage` 即 `FileSystemStorage`，`path()` 恒可用 | `config/settings/base.py` 无 `STORAGES` |

## 2. 目标与非目标

**目标**：① 详情页 Markdown 渲染正文含行内图；② 压缩流量（WebP + 尺寸上限 + 懒加载 + 长缓存 + 移除 pdfjs + 读者零 markdown 依赖）；③ 向后兼容存量与旧归档包；④ 归档端到端支持正文与内联图（可回导、可回滚、幂等）。

**非目标**：WYSIWYG；多尺寸 srcset/AVIF；CDN/防盗链；批量 PDF→Markdown；正文全文检索。

## 3. 数据模型变更

- `Article` 新增 `content = models.TextField(blank=True, default='', verbose_name='Markdown 正文')`（迁移 `0004`）。
- `Article.file` / `Article.file_name` 改为可空：`blank=True, default=''`。
  - `default` 是 **Python 侧默认**，不写 DB 默认；`blank` 只影响校验；`content` 是 ADD COLUMN。
  - **迁移前备份** `db_data/db.sqlite3`（`AlterField` 在 SQLite 上整表重建，30 行无碍但短暂锁表）。
- **不新增 `InlineImage` 模型**（内联图即 `MEDIA_ROOT/inline/` 下的媒体文件），**也不新增 content 哈希列**（幂等在 Python 侧比对，见 §7.5）。
- 上限：`content` ≤ **200_000 字符**；**单篇内联图 ≤ 50 张**。

## 4. 内联图片上传与压缩（后端）

新端点 `POST /api/v1/admin/articles/images/`（`StaffJWTAuth`，multipart `image`）。**与归档导入共用 `articles/images.py`**。

**统一签名（与既有 `process_cover` 同形，供上传端点与归档导入共用）**：`process_inline_image(data: bytes, ext: str, lim) -> (bytes, warnings)`；上传端点侧再包一层 `UploadedFile`。

1. 扩展名 ∈ `{jpg, jpeg, png, webp}`；源字节 ≤ 10MB。
2. **canonical 判定（固定点，防重演「每轮重写」）——必须在任何变换之前、对原始输入做**：**同时满足**「`img.format == 'WEBP'`」+「最长边 ≤1920」+「原始输入无 EXIF 标签」+「无 ICC profile」→ **原样返回原始字节**（不 transpose、不重编码）。⚠️ 若放到 `exif_transpose()` 之后再判，EXIF 已被剥掉，会误判 canonical 并返回**仍含 EXIF 的旋转原图**（元数据泄露 + 每轮重写）。
3. **先 `Image.open()` 读 `img.size` → 查像素 ≤ 80MP → 再 `img.load()`**；`DecompressionBombWarning` 升级为异常；`img.format` 与扩展名一致。
4. `Orientation` **标签值** ≠1 才 `exif_transpose()`。
5. 模式归一：`P`→（有透明→`RGBA`，否则 `RGB`）；`LA`→`RGBA`。
6. `thumbnail((1920,1920), LANCZOS)`。
7. **显式删除 `img.info['exif']` / `icc_profile`** → 编码择优：JPEG → 有损 WebP `q80, method=6`；PNG → 无损与有损取更小者；WebP（不满足 canonical）→ 有损 `q80`。
8. 编码后 ≤ 8MB。canonical 定义是「导出→导入→再导出」收敛的唯一依据，须有幂等测试钉住。

`store_inline_image(canonical_bytes) -> rel_path`（内容寻址 + 原子落盘）：
```python
name = f"{sha256(canonical_bytes).hexdigest()[:32]}.webp"
rel  = f"inline/{name}"
if default_storage.exists(rel):
    return rel                                   # 复用；⚠️ 不 touch mtime（勿假设它会刷新）
abs_path = default_storage.path(rel)             # ⚠️ 必须绝对路径，CWD 不是 MEDIA_ROOT（F24 保证可用）
os.makedirs(os.path.dirname(abs_path), exist_ok=True)   # os.open 不建父目录
tmp = f"{abs_path}.{uuid4().hex}.tmp"            # 同目录 → os.replace 原子
写满 tmp → os.chmod(tmp, 0o644) → os.replace(tmp, abs_path)
```
- **不用 `Storage.save()`**（F18 随机后缀），**不依赖 `FileExistsError`**；`os.replace` 原子且幂等（内容寻址 ⇒ 同内容覆盖安全），消除半成品污染。
- **限定本地 `FileSystemStorage`**（F24；断言类型）；切远程存储须重审并写入 DESIGN。
- 文件名完全由内容决定（T9）；并发同图上传得同一 URL。
- 返回 `{ url: '/media/inline/<name>', width, height, bytes, original_bytes }`。
- **上传不纳入补偿、不纳入 `post_delete`**；孤儿交 `purge_inline_images`（§7.7）。

## 5. 渲染与 API（服务端渲染 + 服务端消毒）

### 5.1 渲染管线（后端，单一实现）
- 依赖：`markdown`（Python-Markdown）+ `nh3`。
- 管线：Python-Markdown（`fenced_code`、`tables`、`sane_lists`）→ 得 HTML → **`nh3.clean()` 只做白名单消毒**（标签 `p,br,h1-h6,ul,ol,li,blockquote,pre,code,a,img,strong,em,del,hr,table,thead,tbody,tr,th,td`；属性 `img[src,alt,title]`、`a[href,title]`、`code[class]`、`th[align]`、`td[align]`；协议 `http,https,mailto`；**`link_rel=None`**）→ **服务端 HTML 解析器回填属性**：给 `img[src]` 加 `loading="lazy" decoding="async"`；给 `a[href]` 加 `target="_blank" rel="noopener noreferrer"`（仅当 src/href 通过本地路径或 http(s) 校验）。
  - ⚠️ 回填器必须 **`html.parser.HTMLParser(convert_charrefs=False)`**，**只在 `handle_starttag` 追加属性**，`handle_data`/`handle_entityref`/`handle_charref` **原样回写**——否则会把 nh3 已转义的 `&lt;` 解回 `<`，等于**在消毒之后重新引入标签**；同时正确处理 void 元素与属性值转义。
  - ⚠️ **唯一顺序（计划 B 生效时尤其关键）**：`渲染 → nh3 消毒 → 还原真实 URL（占位符 → /media/inline/…）→ 回填属性 →（导出时）提取`。**还原必须早于回填与提取**，否则 `src` 仍是占位符：属性回填会因「src 不是本地/http(s)」而跳过（丢 `loading/decoding`），§7.2 提取器也会把占位符当 src（**导出静默漏打包图片**）。此顺序须有测试钉住。
- ⚠️ **事实修正**：Python-Markdown **没有 `html:False`**（那是 markdown-it 的），原始 HTML 默认透传 → **nh3 是唯一消毒边界**；不得以为"渲染器已禁 HTML"而放松 nh3。
- ⚠️ **P1 spike 决策门（本方案唯一遗留高风险）**：先写测试确认 **nh3 是否保留相对 `src="/media/inline/…"`**。
  - 通过 → 按上述管线（属性由我们回填，**不依赖 nh3 保属性**）。
  - 不通过 → **计划 B（仅替换 URL 策略，不自研 sanitizer）**：**仍用 nh3 做标签/属性消毒**，只把 `src`/`href` 的放行改由我们控制——渲染后对 `media/inline/` 图片做 **占位符 ↔ 真实相对 URL 的两段式**处理（消毒时用无害占位，消毒后精确还原），避免自建 sanitizer 引入 mXSS 面。两条路都必须有测试钉住「正文图片不被剥掉」与「`javascript:`/`data:` 被剥掉」。
- ⚠️ **线程安全**：`Markdown.convert()` 改内部状态，gthread 多线程（F19）→ **每请求新建渲染器实例**。
- 渲染+消毒只在服务端；前端仅 `v-html` 服务端已消毒 HTML。读者端**不引入 markdown-it / sanitize-html**。

### 5.2 接口

| 接口 | 变更 |
|---|---|
| `GET /api/v1/articles/{slug}/` | `ArticleDetailOut` 新增 `content_html: str` |
| `GET /api/v1/admin/articles/{id}/` | 新 `AdminArticleDetailOut`：`content`（原始 Markdown）+ `content_html` |
| `POST /api/v1/admin/articles/` | `attachment: UploadedFile = File(None)`；`ArticleCreateIn` 新增 `content: str = ''` |
| `PUT /api/v1/admin/articles/{id}/` | `ArticleUpdateIn` 新增 `content: str | None = None`（MISSING 哨兵） |
| `POST /api/v1/admin/articles/preview/` | **新增**（Staff，JSON `{content}` → `{content_html}`）；入参限长 ≤ 200k + **独立 `limit_req_zone`** |
| `POST /api/v1/admin/articles/images/` | **新增**（§4） |
| 列表 / 搜索 | 不变（不含正文） |

实现要点：
- `article_to_out`：`file_url = article.file.url if article.file else None`；`article_to_detail` → `content_html=render_markdown(article.content)`；`article_to_admin_detail` 额外带 `content`。
- `create_article`：attachment 为空 → 不落盘、`file_name=''`、`file_sha256=''`；补偿只清理**已落盘**的封面/附件。
- **统一校验（A5）**：create / update 在 API 层、导入在 **planner** 层，按**最终状态**断言「`content.strip()` 非空 或 `file` 非空」；update 判更新后状态，导入判「包内字段 ∪ 目标既有状态」。**不放在 `validate_package`**（它不查库，会误拒合法 update，F20）。
- `content` 超长 → 400（API 层）；导入侧由 `validate_package` 判 intrinsic 上限。
- **路由顺序**：`/admin/articles/images/`、`/preview/` 均为单段，与 `/admin/articles/{article_id}/` 同形 → 必须注册在详情路由**之前**（F11）。新增回归测试钉住。

## 6. 前端展示

依赖**移除**：`vue-pdf-embed`、`pdfjs-dist`（同步 `package-lock.json`、删 `front/components/PdfViewer.vue`）。**不新增**客户端 markdown 依赖。

- `front/pages/article/[slug].vue`：
  - **`const slug = computed(() => route.params.slug as string)`**（F12：原为常量，必须改，否则切换文章复用旧数据）。
  - 取数 **`useAsyncData(() => 'article-' + slug.value, fetcher, { watch: [slug] })`**。
  - 正文 `<div class="md-body" v-html="article.content_html" />`；CSS `.md-body img { max-width:100%; height:auto; }`。
  - 回退：`content_html` 为空 → 有 `file_url` 则「附件下载入口」；否则「暂无正文」。删除 `isPdf`/`fileExt` 与 `PdfViewer`。
  - 已知取舍：`useAsyncData` 会把数据序列化进 `__NUXT__`，正文在首屏 HTML 出现两次（占比小）。
- `front/composables/useApi.ts`：**server 端不调用 `navigateTo`**（SSR 阶段不合法），改抛 `createError({ statusCode: 401 })`；客户端维持跳登录页。
- `ArticleForm.vue`：Markdown 文本域（等宽）+「预览」按钮（**仅点击触发**，避免 200k 字符卡顿）+ `v-html` 预览；去掉「请上传附件」校验、附件可选、封面仍必填、文案更新；`buildFormData` 追加 `content`。

## 7. 归档导入/导出兼容（改动面最大）

### 7.1 格式与常量
显式常量（集中一处，消灭 F21）：
- `ARTICLE_SCHEMA_EXPORT = 'myblog.article/v2'`（我们写出）
- `ARTICLE_SCHEMAS_ACCEPTED = {'myblog.article/v1','myblog.article/v2'}`（接受；v1 无 content/images → 缺失 + warning）
- `ARCHIVE_SCHEMA_EXPORT = 'myblog.archive/v2'`；`ARCHIVE_SCHEMAS_ACCEPTED = {v1, v2}`；`REPORT_SCHEMA`（API 报告输出，显式固定）

同步点：`format.py:131`、`api.py:702`、`importer.py:50`、`tests/test_archive_export.py:116`、`tests/test_archive_import.py:350`（v1 fixture，bump 后会新增 schema warning，需核对断言）、`front/types/api.ts`、`scripts/seed_demo.py:374-407`（导出/演示 payload 需补 `content` 键；`:375/:424` 用的是 `SCHEMA_*` 常量，会**自动跟随**，无需改）。**`ignored_on_import` 无需改动**（content/images 属要导入字段）。

`article.json` 追加：`content`（可选）、`images: [{file, sha256, size}]`（可选）；`attachment` 可为 `null`。
包布局：`articles/NNN-<slug>/{article.json, cover.<ext>, attachment.<ext>?, images/<32hex>.webp}`

### 7.2 图片提取器（唯一实现）
`articles/archive/inline.py`：**渲染并 nh3 消毒后，从最终 HTML 解析 `<img src>`**，归一化：
取 path 段（去 scheme/host、去协议相对）→ `unquote()` → `posixpath.normpath()` → **无前导 `/` 则补上** → `lower()` → 匹配 `/media/inline/` 前缀 → 取 basename → 去重。
- 不用 markdown AST（原始 HTML 图被 stash 成占位符，树里无 `<img>`）。
- **导出打包、`skip` 补齐、`purge_inline_images` 三处共用。**

### 7.3 导出
1. 提取图片 URL；逐个读盘算 sha256、写入 `images/<name>`；缺失 → warning；非 `/media/inline/` 引用 → warning。
2. **回滚包与导出共用同一 builder**，回滚包同样含 content 与 images 前态。
3. **实际计数与字节（唯一口径）**：删除 `entries_per_article()` 与 `limits.py:82` 的 `count*3`；新增 `estimate_from_articles()`：
   - **entries** = 固定成员 `manifest.json` + `README.md`（+2）+ 每篇实际成员（`article.json` + 封面 + 可选附件 + 每张实际存在的图）——与导入 `_check_infos`（`validate.py:237` 按**全部文件**判）同口径；
   - **bytes** = **生成型成员的真实字节**（`article.json` 对每篇**序列化后**取 `len(utf8)`、`manifest.json`、`README.md`）+ 磁盘媒体真实字节。⚠️ **不能只累加 `default_storage.size`**（`export.py:100-113` 现状）：`article.json`/`manifest.json`/`README.md` 是**现生成、不在磁盘**的，正文 200k 字符/篇时可达数百 MB，只算磁盘会让导出放过而导入 `budget.charge`（`validate.py:67-72,191`）拒绝 = 自产自拒；
   - ⚠️ 序列化必须**复用导出同一份调用**（`json.dumps(payload, ensure_ascii=False, indent=2) + '\n'`），否则 CJK 被转成 `\uXXXX` 会放大数倍，导致合法的大正文包被 estimate 误拒。注：导入 `budget.charge` 实际只计 `article.json` + 媒体（不计 manifest/README），故 estimate 多算 manifest/README 属**保守安全**；
   - 门禁一律用实际 `entries` / `total_uncompressed`，**导出与导入用同一实际总数**。
   - `ARCHIVE_MAX_ARTICLES_PER_EXPORT=1000` **保留为 blocker**，但明确 **`entries` 才是唯一有效约束**：无图时 `(2000-2)/2 ≈ 999` 篇封顶，有图时 `(2000-2)/53 ≈ 37` 篇封顶（每篇最多 53 成员 = article.json + 封面 + 附件 + 50 图）；该常量恒不先触发，属冗余但无害的粗过滤（保留以免改接口/前端，F23）。
4. **导出自检**：生成的 `article.json` 超 `ARCHIVE_MAX_JSON_BYTES` → 400 明确报错。

### 7.4 导入
1. `_resolve_media` / `validate.py`：**附件角色可缺省**；封面仍必填。
2. **校验不驻留字节（F20/F22）**：`MediaRef` 只保留 `file`（包内相对路径）、`stored_sha256`（**重编码后落盘字节**哈希，D24 语义，幂等/替换判定的唯一依据）、`size`；**不保留原始字节**。**暂存 zip 路径传入 `execute_plan`**，importer 按需重开 zip 取字节。
   - ⚠️ **比对必须用「产物的字节」**：importer 重读的是 zip 内**原始字节**，而 `stored_sha256` 是**重编码后**的哈希 → 必须先重跑 `process_cover()`（封面）/ `process_inline_image()`（内联图）得到规范字节，再用**该产物**的哈希与 `stored_sha256` 比对；不一致则该篇失败。直接把原始字节哈希与之比对会让所有需重编码的文件恒不等而误判（这正是 v0.6 的隐藏口径错误）。
3. 内联图：importer 按需读字节 → `process_inline_image()` → `store_inline_image()`（§4，原子、内容寻址）：正文原 URL 名 == 内容寻址名（我方导出正常路径）→ **URL 不改写**，天然幂等；不等 → 用**文章目录作用域**的 `{old_url: new_url}` 映射做 **URL 字面量精确替换**。
4. **intrinsic 上限在 stage 判**：`validate_package` 逐篇产 errors（`content` ≤200k 字符、单篇图 ≤50）→ 预检即真相。**「至少一项」不放这里**（见 §5.2，避免误拒 update）。
5. 声明了 `images/` 却缺失、或正文引用未被打包 → **warning**。
6. **补偿只针对封面/附件**：inline 是内容寻址、幂等、可重物化，**不纳入 `written`**（否则会误删其他文章在用的同内容图，F22）→ 孤儿交 purge。
7. 图片计入 entries / total_uncompressed / member_bytes（§7.3.3 同一套规则）。
8. **`skip` 也要补齐**：命中已存在文章走 skip 时，若正文引用的 inline 缺失，按内容寻址名**重新物化**（幂等无副作用）。

### 7.5 幂等
- `_identical_article` 键扩展为 `(slug, cover_image_sha256, file_sha256, content_hash)`，**容忍空附件**。
- **实现方式**：因 DB 无 content 哈希列（F15），先按 `slug` 取候选，**在 Python 中比对 `sha256(content)`**；**仅当包内存在 `content` 键时**纳入比对（v1 包无 content → 跳过，不受影响）。

### 7.6 容量配平
- 单篇图 ≤ **50**；`ARCHIVE_MAX_ENTRIES` 500 → **2000**；`TOTAL_UNCOMPRESSED` 500MB → **1 GiB**；`JSON_BYTES` 256KB → **2 MiB**；`MEMBER_BYTES`(50MB)/`UPLOAD`(1GB)/压缩比(100) 不变；`ARTICLES_PER_EXPORT=1000` 保留且与 entries 对齐（§7.3.3）。
- **压缩比校验排除 `article.json`**（大段重复正文易被 `validate.py:174` 误判）。
- 前提：§7.4.2「校验不驻留字节」先落地，否则抬高的上限会放大 OOM（F19/F20）。

### 7.7 孤儿图片回收（单一 owner + 回收站）
- **唯一实现者 = `purge_inline_images`**（离线/定时）；`post_delete`/上传/导入补偿都**不碰** inline 文件。
- 流程：
  1. **pass-1**：§7.2 提取器**一次性载入全库 content** 汇总引用集；**同时**用「DB 原始 `content` 的 `/media/inline/` 字面量扫描」做**交叉校验**（两法互为佐证，任一非空即认为引用集有效）；
  1b. **fail-closed 守卫（必须，但条件收窄以免自反噬）**：仅当 **「提取器为空 **而** 字面量扫描非空」**（= 提取器系统性失效的真实信号，如渲染异常/nh3 行为漂移）→ **中止并报错退出，绝不删除任何文件**（否则会把全库 inline 图当孤儿批量删除 → 全站正文图 404）。
  - **两法双空**不得触发守卫：那表示**确实没有引用**（例如用户清空/删除了所有正文），应放行至回收站（且 pass-2 仍可归还，非硬删）。若不放行，purge 作为 inline 唯一 owner 会**永久无法清理**，回收路径死锁。
  - 另提供显式逃生口 **`--force`**（跳过守卫，仍走回收站 + pass-2，永不硬删），用于确认提取器可信但双法行为异常的场景；
  2. 候选 = 未被引用 **且 mtime 早于宽限期（默认 24h）**；`os.makedirs(trash_dir, exist_ok=True)` 后 `os.replace()` 移入 **`MEDIA_ROOT/_inline_trash/<run_id>/`**（同卷，原子）；
  3. **pass-2**：再次载入全库 content（含字面量扫描），把已重新被引用的候选**从回收站归还**；
  4. 回收站中**仍未被引用**且存在超过宽限期的条目才真正删除。
- 成本：两次全库扫描（个人博客量级可忽略）；默认 dry-run，`--delete` 才执行。
- `_inline_trash/` 必须由 nginx **显式拒绝访问**（§9）。

## 8. 流量优化（用户核心诉求）

| 手段 | 收益 | 位置 |
|---|---|---|
| 原图 → WebP（PNG 无损/有损择优） | JPEG 再省 25%~35%；PNG 截图常 50%+ | §4 |
| 最长边 ≤1920 | 手机原图降载 70%+ | §4 |
| `loading="lazy"` | 只加载进入视口的图 | §5.1 |
| nginx `/media/inline/` 长缓存 immutable | 复访图片 0 流量 | §9 |
| 读者端**零 markdown 依赖** | 不下发 markdown-it/sanitize-html | §5 |
| 详情页路由 chunk 移除 `pdfjs-dist` | 该路由 chunk 减少数百 KB | §6 |
| `useAsyncData`（key 含 slug） | 消除客户端二次拉取全文 | §6 |
| JSON gzip（既有） | 文本传输很小 | nginx 既有 |
| 二期可选：srcset 多尺寸 | 移动端再省一截 | 非目标 |

## 9. 部署 / nginx

```nginx
limit_req_zone $binary_remote_addr zone=preview:10m rate=5r/s;

# 回收站与内部目录一律拒绝（必须在 /media/ 之前，用 ^~ 阻止正则/前缀回退）
location ^~ /media/_inline_trash/ { return 404; }

location /media/inline/ {
    alias /media/inline/;
    add_header Cache-Control "public, max-age=31536000, immutable" always;
    add_header X-Content-Type-Options "nosniff" always;
}
location /api/v1/admin/articles/preview/ {
    limit_req zone=preview burst=10 nodelay;
    proxy_pass http://app:8000;
    # ...proxy_set_header 逐条重复（不继承）
}
```
- 不用 `expires`（会另发一条 `Cache-Control`，叠加成两个头）。
- **运维（F17）**：`scripts/blog.sh` 在 nginx 配置变更时显式 `nginx -s reload`；前端依赖变更 → 重新 `npm ci` 构建并重新导出离线镜像。
- **`seed-media` 无需改动**（F14：整目录拷贝）。

## 10. 安全

- **XSS**：服务端渲染 + **nh3 唯一消毒边界**；`loading/decoding/target/rel` 由我们回填，不依赖 nh3 保属性；相对 URL 保留行为有 spike 测试与计划 B。
- **上传**：Staff 鉴权 + 扩展名/体积/像素（先查后 load）+ 重编码 + **内容寻址 + 临时文件 `os.replace` 原子写**。
- **归档**：内联图导入复用同一校验+重编码；文件名由内容哈希决定（T9）；校验期不驻留字节，importer 重读并比对哈希；回收站目录 nginx 拒绝访问。
- **preview**：入参限长 + 独立限流。
- **裸 URL 泄露**：`/media/inline/` 无鉴权（与现状 `/media/` 一致，接受）。

## 11. 兼容与迁移

- 迁移 `0004`：加 `content`；`file`/`file_name` 加 `blank/default`。**先备份 SQLite 库**。
- 正文为空 → 详情页回退附件下载（A2）。
- 旧归档包（v1）→ 缺失处理 + warning；幂等键对 v1 不受影响（§7.5）。
- **既有测试需核对/调整**：`tests/test_create_article.py`（附件必填断言反转）、`tests/test_update_article.py`、`tests/test_archive_export.py:116`（v1 断言）、归档相关（`entries_per_article`、estimate、幂等键、缺附件、schema）。

## 12. 测试计划

| 层 | 用例 |
|---|---|
| CRUD | content 创建/更新/清空/超长 400；无附件创建成功且 `file_url` 为 null；create/update 最终态为空 → 400；**导入 update 只改标题不被误拒** |
| 渲染 | Markdown → HTML；`<script>`/`onerror`/`javascript:`/`data:` 被剥离；**相对路径图片未被剥掉**；`img[loading=lazy][decoding=async]`；外链 `target/rel` 成对且不被 nh3 覆盖；`code[class]`/表格 `align` 保留；**回填后 `&lt;`/实体未被解回标签（`convert_charrefs=False`）**；并发渲染无串话 |
| 上传 | staff 403 / 非图 400 / >10MB 400 / 像素炸弹先拒不 OOM；EXIF 被剥离；≤1920；输出 WebP；PNG 择优；**同图二次上传同名；并发同图上传同名；进程被杀不留半成品**；**canonical 固定点：规范化后的 WebP 再走一遍仍原样（不每轮重写）；带 Orientation 的 WebP 不被误判 canonical（EXIF 不得残留）**；`store_inline_image` 对非 WebP 字节断言失败 |
| 路由 | `/admin/articles/images/`、`/preview/` 不被 `{article_id}` 吞 |
| 归档导出 | v2 schema；content 入 JSON；images 目录与 sha256；缺失图 warning；**estimate 的 entries 含 +2 固定成员、bytes 含「序列化后的 article.json/manifest/README」真实字节**，与导入 `_check_infos`+`budget.charge` 口径一致（大量正文的包不得自产自拒）；article.json 超限明确报错 |
| 归档导入 | content 恢复；images 重编码落盘；同包重导幂等；URL 改写按文章作用域；v1 旧包告警但可用；**intrinsic 超限在 stage 报错**；缺附件可导入；**skip 补齐缺失图**；**校验期峰值内存有界**；**重读原始字节后重跑 `process_*`，再用产物哈希与 `stored_sha256` 比对**（需重编码的封面不得误判失败） |
| 幂等 | `create_new` 对改过正文不再误判 identical；无附件可判 identical；**stored_sha256 为落盘字节**（封面不被每轮重写）；v1 包不受 content 键影响 |
| 回收 | purge 不误删在用图 / 宽限期内不删 / **扫描后新增引用经回收站归还** / 无前导斜杠与绝对路径形态不漏判 / **`_inline_trash` 经 nginx 返回 404** / **fail-closed：仅「提取器空 + 字面量非空」时中止不删** / **双空时能正常清理（正文全清空后 `--delete` 可完成，不死锁）** / `--force` 走回收站不硬删 |
| 部署 | nginx 变更后 reload 生效；preview 独立限流生效；SSR 401 走 createError 而非 navigateTo |
| 回归 | 全量 `pytest`、`ruff`、`mypy`、`vue-tsc` |

## 13. 文档同步

`DESIGN.md`（模型表、5.x API、渲染管线与「nh3 为唯一消毒边界 + 属性回填」、媒体与 nginx 规则、schema 常量、上限新值、`FileSystemStorage` 前提、回收站目录）、`AGENTS.md`（附件可选、content、图片端点、原子写与路径基准、线程安全渲染、`slug` 必须用 computed、新坑点）、`TEST.md`、`docs/ARTICLE_IMPORT_EXPORT.md`（v2 格式、附件可缺省、上限调整、purge 回收站语义、校验不驻留字节、压缩比排除 JSON、门禁口径）、`README.md`。

## 14. 实施阶段

| 阶段 | 内容 | 主要文件 |
|---|---|---|
| P0 | 迁移（含备份）+ 模型 + schemas + content CRUD + 附件可选 + 最终态校验 | `articles/models.py`、`migrations/0004_*.py`、`articles/schemas.py`、`articles/api.py` |
| P1 | **spike：nh3 相对 URL 行为** → 渲染管线（markdown+nh3+属性回填，每请求实例）+ public/admin/preview | `articles/rendering.py`(新)、`articles/api.py`、`pyproject.toml` |
| P2 | 图片处理（`process_inline_image` + `store_inline_image`）+ 上传端点 + purge 回收站命令 | `articles/images.py`(新)、`articles/api.py`、`management/commands/purge_inline_images.py` |
| P3 | 前端：详情页 computed slug + useAsyncData(key/watch)/v-html、useApi SSR 401、表单预览、移除 pdfjs | `front/pages/article/[slug].vue`、`front/composables/useApi.ts`、`front/components/admin/ArticleForm.vue`、`front/types/api.ts`、`front/package.json` |
| P4 | 归档 v2（常量 / 提取器 / 实际计数 / 导出 / 导入 / 校验不驻留 + zip 接入 + 哈希比对 / stage intrinsic 上限 / planner 最终态 / 幂等 Python 比对 / 容量 / skip 补齐 / 回滚共用 builder） | `articles/archive/*.py`、`articles/signals.py`、`config/settings/base.py` |
| P5 | nginx（含 `_inline_trash` 拒绝）+ blog.sh reload + 文档 | `docker/nginx/nginx.conf`、`scripts/blog.sh`、`DESIGN.md` 等 |

## 15. 残留风险（无法根除）

- 单尺寸无 srcset：移动端仍下载 1920 宽图。
- 无 width/height 预留 → CLS。
- SSR 载荷使正文在首屏 HTML 出现两次（占比小）。
- `/media/inline/` 无鉴权，URL 泄露即可访问。
- **内网穿透代理是否透传长缓存策略未知**；若不透传，长缓存只对直连有效（需实测）。
- purge 在 pass-2 之后才建立的引用仍可能被误删（窗口极窄，无全局锁的固有代价）；**且复用分支不 touch mtime，宽限期只保护"新文件"，不保护"旧图被重新引用"**——已用回收站 + 归还缓解，未归零；**但"提取器整体失效导致批量误删"这一灾难场景已由 fail-closed 守卫（条件收窄为「提取器空 + 字面量非空」）+ 字面量交叉校验 + `--force` 出口兜底**。
- 服务端渲染有每请求 CPU 成本（个人博客量级可忽略）。
- 手改包把图片换成与正文 URL 名不符的内容时依赖 URL 字面量精确替换；极端转义形式可能漏改。
- 原始 HTML 透传意味着**安全完全依赖 nh3 白名单配置的正确性**；nh3 对相对 URL 的保留行为由 P1 spike 决定，若走计划 B 则用「占位符 ↔ 真实 URL 两段式」绕开 ammonia 的 URL 策略（仍由 nh3 消毒，不自研 sanitizer）。
- 回收站 `MEDIA_ROOT/_inline_trash/` 会被 `cp media/.`（seed-media）与整目录备份一并搬运（nginx `^~` 只挡访问面，不挡复制）。
- `store_inline_image()` 绕过 Django storage，仅适用本地 `FileSystemStorage`；权限受 umask 影响，已显式 `chmod 0o644`。