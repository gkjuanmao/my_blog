# 文章导入 / 导出（ZIP 归档）方案 — v3 定稿

> **状态：方案已定稿，尚未实现。** 本文是实现前的设计产物；实现完成后，API 契约并入 `DESIGN.md`（新增 5.3.4），本文保留为格式与决策的详细依据。
>
> **版本**：v4（2026-09-30）
> v1 → v2：对抗式自审挑出 36 条遗漏（含 3 处实质性设计错误）
> v2 → v3：**三方独立红队**（安全 / 数据 / 运维）挑出 32 条
> v3 → v4：**第二轮独立验证**（逐条闭合审计 + 攻击 v3 自身）又挑出 18 条新增 + 14 项未闭合，全部已合并；**修正了 v3 中 3 处我写错的事实**（路由遮蔽、鉴权时序、像素指纹），映射见 §14
>
> **v4 相对 v3 的关键修正**：
> 1. **路由顺序**：`/admin/articles/export/` 会被 `/admin/articles/{article_id}/` 拦截（实测 `resolve()` → `{'article_id': 'export'}`，无 int 转换器）→ 归档路由必须注册在详情路由**之前**，并加路由回归测试钉住。
> 2. **幂等键**：像素指纹**不成立**（JPEG q88 重编码后像素改变；`mode='P'` 时 `tobytes()` 只是索引）→ 改为在 Article 上新增两列记录哈希；**v4.1 实测又发现**“无条件重编码 + 源字节哈希”会使导出→导入→导出→导入每轮重写 → 定为“**按需重编码 + 存储字节哈希**”（§4.6）。
> 3. **导入锁**：SQLite 上 `select_for_update` 是**静默空操作**（`has_select_for_update=False`，`FOR UPDATE` 被丢弃）→ 改为 **Redis/cache `SET NX PX` + owner token + TTL**。
> 4. **回滚包可用性**：必须定义内容范围与"如何施加"，且触发条件改看 **plan 里是否有覆盖动作**（不再看全局策略字符串）。
> 5. **导出可回导性**：导出上限必须与导入上限共用同一组常量（v3 的 1000 篇 vs 导入 500 条目录约束 → 约 166 篇即不可回导）。
> 6. **nginx 片段**：v3 的 `limit_req zone=archive:1r/s` 实测 `[emerg]`；`limit_conn_zone` 漏声明；`/export/` 缺长超时。
> 7. **entrypoint**：`mkdir -p a/{b,c}` 在 dash 下不展开。
>
> **面向**：实现者（AI 或人）。所有"决策"已与产品负责人逐条确认（§1），实现时不应再自行改变。

---

## 0. 目标与非目标

### 目标

1. 在后台文章管理页，把**一篇或多篇文章**导出为单个 ZIP，包内含该文章的**全部信息**（元数据 + 封面 + 附件）。
2. 该 ZIP 可**再次导入**本系统（往返可用），且**导出必须保证可回导**（§6.2 用与导入同一组上限做拦截）。
3. ZIP **可人工编辑**（改元数据、换媒体、删/加文章），编辑后重新导入仍然可用。
4. 导入有**预检**（不落库、不落盘），可查看逐篇动作与警告后再确认执行。

### 非目标（明确排除，避免误解）

- **不是灾难恢复备份**。`views`、`created_at`、`updated_at` **不恢复**（决策 D3）；导进新库 ≠ 站点还原。真正的灾难恢复是"数据库 dump + media 打包"，属独立功能。
- 不导入用户账号（只按 username 关联已有用户，绝不建号）。
- 不导入分类/标签的"改名"（只按 slug 复用，绝不修改既有分类/标签的名称与描述）。
- 不做异步/队列化的超大包处理（当前无 Celery；限制见 §5.2，超限直接拒绝并提示）。

---

## 1. 决策清单（已锁定）

| # | 决策 |
|---|---|
| D1 | 导入冲突默认策略 `skip`（按 `slug` 匹配） |
| D2 | 两步流程：预检（dry-run）→ 确认 |
| D3 | `views` / `created_at` / `updated_at` **导出但不恢复**，在 `manifest.json` 里用 `ignored_on_import` 显式声明 |
| D4 | 分类/标签不存在时自动创建（每包各 ≤ 50 个） |
| D5 | 包内附 `README.md`（手改说明书） |
| D6 | 附件强制下载（防御 HTML 类内容） |
| D7 | nginx 归档路径 `client_max_body_size 1g` |
| D8 | 导出同时支持"仅选中"与"按当前筛选全部" |
| D9 | 单篇 `import.action` 可覆盖全局策略（`auto` = 用全局） |
| D10 | 目录名 `NNN-<slug>`（ASCII） |
| D11 | 提供"全部以草稿导入"开关（默认关） |
| D12 | `category: null` / `tags: []` **保真**（不注入默认分类/标签） |
| D13 | 导出下载用**一次性票据 URL**（不走浏览器 blob） |
| D14 | 非 `skip` 导入前，服务端自动生成**回滚包** |
| D15 | HTML 强制下载规则**只作用于 html/htm 附件**（见下方更新） |
| **D16** | **在 `docker-compose.yml` 新增 `redis` 服务**，`REDIS_URL` 供锁/票据/既有登录限流使用 |
| **D17** | 两阶段改为**服务端暂存 + `staged_id`**（避免重复上传 1GB） |
| **D18** | "导入前备份"正式定名**"回滚包"**，并在文档中声明其非完整备份 |
| **D19** | **附件白名单去掉 `html`**（`pdf/doc/docx`），全局生效（含既有创建/更新接口） |
| **D20** | **封面服务端重编码**（`exif_transpose` 后再剥离 EXIF/polyglot） |
| **D21** | 下载票据为**能力 URL**（不绑定 owner，见 P1-A）：TTL 300s + 单次 + `access_log off` + 提供重签端点 |
| **D22** | `as_draft` **只作用于 create**；与其他策略相遇时忽略 + 预检逐条警告（见 P2-A） |
| **D23** | **遗留扩展名逃生通道**（见 P3-A）：导入时额外接受 `html` 并强制下载 + 警告，保证 D19 之前的存量文章（含回滚包）仍可回导；但**上传接口不再接受 html** |
| **D24** | Article 新增 `cover_image_sha256` / `file_sha256`，语义为**当前落盘文件的字节哈希**（含上传与导入两条写入路径），作为媒体幂等与 `create_new` 去重的**唯一**依据 |

> **D15 + D19 的关系**：`html` 从白名单移除后，导入与上传都不再接受 HTML 附件；nginx 的 HTML 强制下载规则**保留**作为对历史数据与纵深防御的兜底（当前 `media/files/` 内 30 个附件全部是 pdf，无历史 HTML，但规则保留无成本）。

---

## 2. 归档格式规范

### 2.1 包布局

```
blog-articles-20260930-011230.zip
├── manifest.json                      # advisory：包级索引与声明
├── README.md                          # 手改说明书（人读；导入时忽略）
└── articles/
    ├── 001-tu-er-qi-ka-pa-duo-qi-ya/  # NNN(3位补零) + slug；仅用于排序与识别
    │   ├── article.json               # 该篇的**唯一真相源**
    │   ├── cover.jpg                  # 封面（扩展名随实际格式）
    │   └── attachment.pdf             # 附件
    └── 002-mi-lu-ma-qiu-bi-qiu/
        ├── article.json
        ├── cover.png
        └── attachment.docx
```

**导入时的发现规则（关键）**：

- **递归**扫描包内任意深度寻找名为 `article.json` 的文件（深度 ≤ 5）。因此"解压 → 编辑 → 重新压缩"时多套一层根目录、或把文章挪到别的子目录，**都不影响导入**。
- 忽略 `__MACOSX/`、`.DS_Store`、`Thumbs.db`。
- **不要求**存在 `manifest.json`（缺失只警告）。manifest 仅作索引/校验辅助。
- 目录名与 `article.json.slug` 不一致 → 以 JSON 为准 + 警告。
- 条目路径统一：`\` → `/`，再用 `PurePosixPath(name).parts` 规范化；含 `..`/绝对段/盘符 → 拒绝。
- 条目名去重：**先做 Unicode NFC + 大小写折叠**再比对，任何重复 → **整包 400**（不给"最后一条生效"的机会）。

### 2.2 `articles/NNN-<slug>/article.json`

```json
{
  "schema": "myblog.article/v1",
  "source": { "id": 30, "exported_at": "2026-09-30T01:12:30+08:00", "app_version": "0.1.0" },
  "title": "土耳其卡帕多奇亚",
  "slug": "tu-er-qi-ka-pa-duo-qi-ya",
  "summary": "热气球在日出前升空，从空中看这片地貌像另一个星球。",
  "publish_time": "2026-08-18T00:00:00+08:00",
  "location": "土耳其·格雷梅",
  "is_published": true,
  "views": 4213,
  "created_at": "2026-08-18T00:00:00+08:00",
  "updated_at": "2026-08-18T00:00:00+08:00",
  "author": { "username": "admin" },
  "category": { "slug": "jing-wai-you", "name": "境外游", "description": "出境自由行的见闻与准备" },
  "tags": [
    { "slug": "she-ying", "name": "摄影" },
    { "slug": "lu-ying", "name": "露营" }
  ],
  "cover":      { "file": "cover.jpg",      "original_name": "土耳其卡帕多奇亚-封面.jpg", "sha256": "a39e…", "size": 25695 },
  "attachment": { "file": "attachment.pdf", "original_name": "土耳其卡帕多奇亚.pdf",      "sha256": "5fe3…", "size": 11144 },
  "import": { "action": "auto" }
}
```

**字段语义**

| 字段 | 必填 | 说明 |
|---|---|---|
| `schema` | 否 | 非 `myblog.article/v1` → 警告但尽力导入（前向兼容） |
| `title` | **是** | ≤200 字符，非空白 |
| `slug` | **是** | 必须通过 Django `SlugField` 校验（`^[-a-zA-Z0-9_]+$`，≤200）；空/非法 → 该篇失败 |
| `summary` | 否 | ≤500 |
| `publish_time` | **是** | ISO8601，**必须带偏移量**（如 `+08:00`）；naive → 警告并 `make_aware` |
| `location` | 否 | ≤255 |
| `is_published` | 否 | **严格布尔**（`"true"`/`"0"`/`null` → 该篇失败，不做宽松解析） |
| `views` | 否 | 仅信息展示，**导入时忽略** |
| `created_at` / `updated_at` | 否 | 仅信息展示，**导入时忽略** |
| `author.username` | 否 | 关联已有用户；查不到 → 回退导入者 + 警告；**绝不建号**；**update 时永不写 author** |
| `category` | 否 | `null` = 无分类（保真）；缺省也视为无分类；对象时 `slug` 必填 |
| `tags` | 否 | `[]` = 无标签（保真）；缺省等同 `[]` |
| `cover` / `attachment` | **是** | 见 §2.5 |
| `import.action` | 否 | `auto`（默认）/`skip`/`update`/`create_new`；非法值 → 警告 + 回落全局策略 |

### 2.3 `manifest.json`（advisory）

```json
{
  "schema": "myblog.archive/v1",
  "generator": { "app": "my_blog", "version": "0.1.0", "django": "6.0.7" },
  "exported_at": "2026-09-30T01:12:30+08:00",
  "filters": { "ids": [1, 30], "count": 2 },
  "ignored_on_import": ["views", "created_at", "updated_at"],
  "limits": { "max_member_bytes": 52428800, "max_total_uncompressed": 524288000 },
  "warnings": ["articles/003-x：封面文件在磁盘上缺失，导入前需补齐"],
  "articles": [
    { "index": 1, "path": "articles/001-tu-er-qi-ka-pa-duo-qi-ya",
      "slug": "tu-er-qi-ka-pa-duo-qi-ya", "title": "土耳其卡帕多奇亚",
      "is_published": true, "updated_at": "2026-08-18T00:00:00+08:00",
      "sha256": { "article_json": "…", "cover": "…", "attachment": "…" } }
  ]
}
```

- 包级 `warnings` 用于记录"导出时发现的问题"（如 DB 有记录但磁盘缺文件）。
- 未知/更高版本的 `schema` → 警告，尽力导入。

### 2.4 `README.md`

自动生成，中英双语，内容固定包含：包结构说明；`article.json` 字段表；**常见手改示例**；**注意事项**（UTF-8 编码、不要写注释与尾逗号、slug 必须唯一且合法、附件仅 `pdf/doc/docx`、封面 `jpg/jpeg/png/webp`、哪些字段导入时会被忽略）；"改完直接重新导入即可"。

### 2.5 媒体字段语义

```json
"cover": { "file": "cover.jpg", "original_name": "我的封面.jpg", "sha256": "…", "size": 25695 }
```

| 键 | 语义 |
|---|---|
| `file` | **包内相对引用**（仅用于在压缩包内定位文件）。**绝不**作为存储文件名使用（见 §5.1 威胁 T9） |
| `original_name` | 展示/下载用的原始文件名；导入时会净化（去路径分隔符与控制字符、≤255） |
| `sha256` | **包内该文件字节**的 SHA-256。导入时校验：不一致 → 警告并以包内字节为准（不阻断） |
| `size` | 包内字节数；校验不一致 → 警告 |

---

## 3. 手改指南（可编辑性矩阵）

| 想做的事 | 操作 | 导入时行为 |
|---|---|---|
| 改标题/摘要/时间/地点/是否发布 | 编辑 `article.json` | 生效（见 §4.2 字段规则） |
| 改分类/标签 | 编辑 `category.slug` / `tags[].slug` | 按 slug 复用；不存在则自动创建（≤50/包）；`null`/`[]` 保持为空 |
| 换封面 | 用同名新文件覆盖 `cover.jpg` | `sha256` 不符 → 警告；非规范格式会被按需重编码后入库 |
| 换附件 | 用同名新文件覆盖 `attachment.pdf` | 直接落盘原字节 |
| 改附件格式（如 docx → pdf） | 改文件名**并**同步 `attachment.file` | 生效（扩展名走白名单） |
| 只改文件名、忘了改 JSON | — | 若该目录下**恰好只有一个**同角色候选文件 → 回退使用 + 警告；**多个候选 → 该篇失败**（不猜） |
| 删掉一篇文章 | 删整个 `articles/NNN-xxx/` 目录 | 该篇不参与导入；manifest 无需同步 |
| 新增一篇文章 | 复制一个目录并改 `article.json`（**slug 必须改**） | 按策略创建 |
| 只想让某篇被覆盖/跳过 | 写 `"import": {"action": "update"}` | 覆盖全局策略 |
| 重新压缩时多套了一层目录 | 无需处理 | 递归发现 `article.json`，正常导入 |

---

## 4. 导入语义

### 4.1 匹配与策略

匹配键：`article.json.slug`（唯一）。

| 策略 | 命中已有 | 未命中 |
|---|---|---|
| `skip`（默认） | 跳过（报告 skipped） | 创建 |
| `update` | 覆盖 JSON 中**存在的**字段 + 按需替换媒体 | 创建 |
| `create_new` | `unique_slug()` 加 `-2`/`-3` 新建；报告**回显最终 slug** | 创建 |

`create_new` 的幂等保护：创建前按 `(slug, 封面像素指纹, 附件 sha256)` 查重，命中即跳过（报告 skipped，原因"内容完全相同"），避免重试造成无限复制。

### 4.2 字段应用规则（create vs update）—— 实现的核心

**统一原则：只有 `article.json` 中"键存在"才应用该字段（`MISSING` 哨兵）。显式 `null` 才置 NULL，显式 `[]` 才清空 M2M。**

| 键 | create | update |
|---|---|---|
| `title` | 必填 | 存在才写 |
| `slug` | 必填（校验 + `unique_slug`） | 存在才写（`unique_slug(exclude_id=…)`） |
| `summary` | 缺省 `''` | 存在才写 |
| `publish_time` | 必填 | 存在才写 |
| `location` | 缺省 `''` | 存在才写 |
| `is_published` | 缺省 `False`；若开启"全部以草稿导入"则强制 `False` | 存在才写；**若开启 `as_draft` 则本条 update 被忽略并记警告**（D22，绝不静默下架已发布文章） |
| `category` | `null` → NULL；缺省 → NULL | 存在才写 |
| `tags` | `[]` → 空；缺省 → 空 | 存在才 `tags.set()` |
| `author` | 解析 username，失败 → 导入者 + 警告 | **永不写** |
| `views` | 忽略（DB 默认 0） | **永不读写** |
| `created_at` / `updated_at` | 忽略 | **永不读写**（`updated_at` 由 `auto_now` 更新） |
| `cover` / `attachment` | 必填 | 存在才替换（幂等判定见 §4.6） |

**update 必须使用 `save(update_fields=… | {'updated_at'})`，禁止整篇 `save()`** —— 整篇 `save()` 会把读取时的 `views` 快照写回，红队已实测复现"并发阅读 +1 被导入改回旧值"（`articles/api.py` 中已有同源注释与先例）。

### 4.3 分类与标签

- 按 `slug` 查已有 → 命中则直接复用（**即使 `name` 不同也只警告，绝不改名/改描述**）。
- 未命中 → 自动创建（`name` 取 JSON，`description` 取 JSON 或空）。`slug` 必须合法，否则用 `generate_slug(name)` 派生并警告。
- 单包新增上限：分类 ≤ 50、标签 ≤ 50。**超限 → 该篇失败**（不做静默回落）。
- 创建动作在**该篇的 `transaction.atomic()` 内**：该篇失败则连带回滚，不留孤儿分类/标签。
- `category: null` / `tags: []` 就是空（决策 D12），不套用 `default-category`/`default-tag`。

### 4.4 作者

- 按 `username` 查已有用户 → 命中即用。
- 未命中或缺失 → 用**当前导入者** + 警告（create 时）；update 时**完全不碰 author**。
- 任何情况下**不创建用户**。

### 4.5 时间

- `publish_time` 必须带偏移量（`+08:00` 或 `Z`）；naive → 警告 + `timezone.make_aware()`（Asia/Shanghai）。
- 非法格式 → 该篇失败。
- `views`/`created_at`/`updated_at` 一律忽略。

### 4.6 媒体处理

**存储名**：永远由 `cover_upload_path()` / `file_upload_path()` 生成（`covers/<uuid>.<ext>`、`files/<uuid>.<ext>`），**任何来自包内的字符串都不得参与存储路径**。

**封面（决策 D20）**：
1. 扩展名 ∈ `{jpg, jpeg, png, webp}`；大小 ≤ 20MB。
2. Pillow `Image.open()` + **`img.load()`**（不只是 `verify()`——红队实测 `PNG + <script>` 能通过 `verify()`）。
3. 校验 `img.format` 与扩展名一致（不一致 → 该篇失败）。
4. 校验像素数 ≤ `ARCHIVE_MAX_IMAGE_PIXELS`（80MP），并把 `Image.DecompressionBombWarning` 升级为异常。
5. 取 `Orientation` **标签值**判断方向（orientation ≠ 1 → `ImageOps.exif_transpose()` 校正 + 警告）。—— 不能看 `exif_transpose` 返回对象是否同一个：Pillow 12.x 在**无** Orientation 时也返回副本（实测），否则每张封面都假阳警告。
6. **按需重编码**（这是关键）：
   - 已是**规范格式**（JPEG 以 `FFD9` 结尾 / PNG 以 `IEND` 块结尾 / WebP 的 RIFF 长度自洽）**且**无方向信息 → **原样存储**；
   - 否则重编码为同格式（JPEG `quality=88,optimize=True`），剥离 EXIF 与尾部附加数据（polyglot），并记警告。
7. 待存储字节再校验大小 ≤ 20MB。

**附件（决策 D19）**：扩展名 ∈ `{pdf, doc, docx}`；大小 ≤ 50MB；**原字节落盘**（不重编码）。

**幂等判定（D24，唯一依据 = 存储字节哈希）**：

- `cover_image_sha256` / `file_sha256` 记录的是**当前落盘文件的字节**哈希，语义就是“这个文件现在的内容指纹”（上传路径的字节 == 落盘字节，所以两条路径语义一致）。
- 判定：`sha256(本次将要写入的字节)` == 该文章已有的 `*_sha256` → **跳过替换**；不等（或列为空/文件丢失）→ 替换并写入新哈希。
- ⚠️ **为什么不能“无条件重编码 + 记源字节哈希”**（真实数据实测发现的缺陷）：导出出去的是**存储字节**，若无条件重编码，则「导出 → 导入 → 导出 → 导入」每一轮都重写并再次损失画质。按需重编码 + 存储字节哈希使往返第一轮就收敛；由 `test_reexport_then_import_update_does_not_rewrite_media` 守住。
- **禁止**用“像素指纹”：实测 JPEG `quality=88,optimize=True` 重编码会改变像素，且 `mode='P'` 时 `tobytes()` 只是调色板索引，不同调色板会误判相同。
- 既有文件**无法解码/已丢失**时，一律视为“不同 → 替换”（不抛异常）。

**`tolerant_media` 回退**：仅当声明的文件在包内找不到、且该目录下**恰好只有一个**同角色候选（封面：图片；附件：`pdf/doc/docx`）时启用，并记警告。**多个候选 → 该篇失败**（不按遍历顺序猜）。

**替换时序**（沿用项目既有 `update_article` 的成熟模式）：校验全部通过 → 落盘新媒体（`save=False`）→ `article.save()` → **成功后才删除旧文件**；异常时只回收**本次新落盘**的文件。

### 4.7 事务与补偿

```python
for item in plan.items:                     # plan 由共享 planner 产出（§4.9）
    written: list[str] = []
    try:
        with transaction.atomic():          # 分类/标签自动创建也在此保存点内
            apply_fields_and_media(item, written)
    except Exception as exc:
        _delete_stored_files(written)       # 只回收本次新落盘的文件
        item.mark_failed(exc)
```

- 磁盘写入**不在事务内**（无法回滚），因此必须有显式的 `finally` 回收 + 启动清扫兜底（§8.5）。
- 单篇失败不影响其余条目；错误逐条记入报告。
- 注释：`post_delete` 信号只在真正删除时触发，**不能**用作补偿手段。

### 4.8 幂等性

| 场景 | 期望 |
|---|---|
| 同一包 + `skip` 连导两次 | 第二次全部 skipped，零副产物（无新文件、无新分类/标签） |
| 同一包 + `update` 连导两次 | **业务字段与文件集合不变**（"稳定"的定义）；`updated_at` 因 `auto_now` 会变化，不计入稳定性，也因此 **manifest 里的 `updated_at` 不参与任何比较** |
| `create_new` 重试同一包 | 按 `(slug, cover_image_sha256, file_sha256)` 查重 → skipped（`skip_reason=identical`），不产生 `-2`/`-3` 副本 |

### 4.9 共享 planner（防两阶段结论不一致）

预检与真实执行**必须走同一个 planner**：同一个函数产出 `[(article, action, warnings, errors, taxonomy_plan)]`，预检只"报告"，执行只"落地"。禁止两套匹配/校验逻辑。

---

## 5. 安全模型

### 5.1 威胁 → 控制

| # | 威胁 | 控制 |
|---|---|---|
| T1 | Zip Slip（`../`、绝对路径、盘符、软链） | 不用 `extractall`；`\`→`/` 归一化 → `PurePosixPath.parts` → 拒绝 `..`/绝对段；`external_attr>>16` 只接受 `S_ISREG`/`S_ISDIR`/mode 0；写入前断言目标路径 `is_relative_to()` 目标目录 |
| T2 | 解压炸弹（CWE-409） | 条目数 ≤500、单文件 ≤50MB、总解压 ≤500MB、压缩比 ≤100:1；**用 `zf.open()` 分块读并统计真实字节**，不信 `ZipInfo.file_size`（红队实测：谎报 1 字节的条目曾吃掉 141MB 内存） |
| T3 | 图片炸弹 / polyglot | 像素数上限 + `DecompressionBombWarning`→异常 + `load()` + `format` 与扩展名一致性 + **服务端重编码** |
| T4 | 加密包 | `flag_bits & 0x1` → 整包 400 |
| T5 | 重复条目名 / 大小写与 NFC 变体 | NFC + casefold 后比对，任何重复 → 整包 400 |
| T6 | 包内 JSON 炸弹 / 超长字段 | `article.json` ≤256KB；逐字段跑模型校验（`max_length`、`SlugField`）——SQLite 不校验 VARCHAR，**不校验就会静默存下超长值** |
| T7 | 未认证者/滥用者消耗 1GB 请求体 | **在 nginx 层**限流限体积（`limit_req`/`limit_conn`/`client_body_timeout`），非归档路径保持小 body 上限。（v3 曾声称 ninja `fix_request_files_middleware` 导致鉴权晚于读体——**已证伪**：`ninja/conf.py:33` 的 `FIX_REQUEST_FILES_METHODS` 只含 PUT/PATCH/DELETE，POST 走 `_run_checks` → `_get_values`，鉴权在前；nginx 限制是纵深防御而非补救。） |
| T8 | 越权（导出草稿 / 破坏性导入） | 新增 `StaffJWTAuth`：在校验令牌基础上要求 `is_staff`；三个归档端点全部挂载 + 测试断言 403 |
| T9 | 包内文件名污染存储路径 | 存储名**永远**由 `cover_upload_path`/`file_upload_path` 生成；JSON 里的 `file` 只作包内引用 |
| T10 | 一次性票据泄露 | 票据存 DB（非缓存）；**放在 URL 路径段**而非 query（nginx access log 实测会记录 query）；该 location `access_log off` + `Referrer-Policy: no-referrer`；TTL 300s + 单次使用 + 绑定 owner |
| T11 | 回滚包/导出产物被匿名下载 | 产物落 `ARCHIVE_ROOT`（**不在任何 nginx alias 下**），只经票据端点流出（红队 3/3 命中：`/media/` 无鉴权 + `expires 7d`） |
| T12 | 异常信息泄露 | 归档错误一律包成 `HttpError(400, …)`；全局 500 不再回显 `str(exc)`，改通用文案 + 服务端日志 |
| T13 | DoS（反复导入/预检） | 导入串行化 + 每用户最小间隔（`ARCHIVE_IMPORT_MIN_INTERVAL_SECONDS`）。 |
| T14 | 并发导入 / 重试重复创建 | **Redis/cache `SET NX PX` 锁 + owner token + TTL**（**不能用** `select_for_update`：SQLite 上 `has_select_for_update=False`、`FOR UPDATE` 被静默丢弃）+ `create_new` 存储字节哈希查重。锁缓存不可用 → **fail-closed 503**。 |
| T15 | 附件内容型攻击（HTML/PDF JS） | 白名单收紧到 `pdf/doc/docx`（D19）；nginx 对 `html/htm` 兜底强制下载；`/media/` 补 `X-Content-Type-Options: nosniff` |

### 5.2 上限与配置（全部为 Django settings，**调用时读取**以便测试覆盖）

```python
ARCHIVE_ROOT = BASE_DIR / 'private_archives'   # 不对外服务
ARCHIVE_STAGING_TTL_SECONDS = 1800
ARCHIVE_TICKET_TTL_SECONDS = 300
ARCHIVE_IMPORT_MIN_INTERVAL_SECONDS = 60

ARCHIVE_MAX_UPLOAD_BYTES = 1024 ** 3            # 1GB（nginx 侧同样限制）
ARCHIVE_MAX_ENTRIES = 500
ARCHIVE_MAX_TOTAL_UNCOMPRESSED = 500 * 1024 ** 2
ARCHIVE_MAX_MEMBER_BYTES = 50 * 1024 ** 2
ARCHIVE_MAX_COMPRESSION_RATIO = 100
ARCHIVE_MAX_PATH_LENGTH = 255
ARCHIVE_MAX_DEPTH = 5
ARCHIVE_MAX_JSON_BYTES = 256 * 1024
ARCHIVE_MAX_ARTICLES_PER_EXPORT = 1000
ARCHIVE_MAX_IDS_PER_REQUEST = 200
ARCHIVE_MAX_NEW_CATEGORIES = 50
ARCHIVE_MAX_NEW_TAGS = 50
ARCHIVE_MAX_IMAGE_PIXELS = 80_000_000
# D23：导入（含回滚包）额外接受的**遗留**附件扩展名；上传接口不接受
ARCHIVE_LEGACY_ATTACHMENT_EXTENSIONS = {'html'}
```

> 上限**同时约束导出与导入**（B1）：导出前先算 `3 × 篇数 ≤ ARCHIVE_MAX_ENTRIES`、总源字节 ≤ `ARCHIVE_MAX_TOTAL_UNCOMPRESSED`、预计 zip ≤ `ARCHIVE_MAX_UPLOAD_BYTES`，任一超限即 400 并提示缩小范围；`estimate` 直接返回 `importable: bool`。
> 所有 `ARCHIVE_*` 均为**调用时读取**（不写死模块常量），以便 `override_settings` 收紧后测试边界。

### 5.3 实证依据索引

红队评审用以下方式取证，实现后应保留同类测试：
- podman 起 nginx 1.27/1.31 验证 location 匹配、`alias` 继承、`Content-Disposition`、access log 行为。
- `gunicorn.config` 内省确认 `workers=1 timeout=30 graceful_timeout=30`。
- 构造"声明 1 字节实解 64MiB"的 zip 测内存峰值；构造 `PNG + <script>` polyglot 测 `verify()` 是否放行。
- 并发阅读 +1 后执行整篇 `save()` 复现 views 回退。
- `default_storage.save('../x.png')` 确认存储层已拒绝穿越。

---

## 6. 接口规范

### 6.1 端点总览

| 方法 | 路径 | 认证 | 说明 |
|---|---|---|---|
| `GET` | `/api/v1/admin/articles/export/` | Staff | 创建导出票据，返回 JSON（**不**直接回 zip） |
| `GET` | `/api/v1/admin/articles/export/estimate/` | Staff | 只返回数量与体积预估 |
| `GET` | `/api/v1/admin/archives/{ticket}/` | **票据**（`auth=None`） | 真正下载（zip 流） |
| `POST` | `/api/v1/admin/articles/import/stage/` | Staff | multipart 上传 zip → 校验 + 暂存 → 返回 `staged_id` + 预检报告 |
| `POST` | `/api/v1/admin/articles/import/commit/` | Staff | JSON `{staged_id, strategy, ...}` → 执行导入 → 结果报告 |
| `DELETE` | `/api/v1/admin/articles/import/stage/{staged_id}/` | Staff | 放弃暂存 |
| `GET` | `/api/v1/admin/articles/import/limits/` | Staff | 返回各类上限，供前端预检 |
| `POST` | `/api/v1/admin/archives/{ticket}/reissue/` | Staff | 重签已过期/已用的导出或回滚票据 |

> **路由顺序（实测）**：`resolve('/api/v1/admin/articles/export/')` → `{'article_id': 'export'}`，因为 `{article_id}` **没有 int 转换器**。因此 `export/` 与 `export/estimate/` **必须注册在 `GET /admin/articles/{article_id}/` 之前**，否则返回 422。
> 用 `tests/test_archive_routing.py` 把每一条归档路径的解析结果钉住（按 view 函数名 + 路径参数断言），防止后人重排路由时静默回归。
> `/admin/articles/import/...` 为 3 段路径，与详情路由（1 段）不可能碰撞。

### 6.2 导出

```
GET /api/v1/admin/articles/export/?ids=1,30
GET /api/v1/admin/articles/export/?keyword=&category_slug=&is_published=&ordering=
```

- `ids` 与筛选参数互斥（同时给出以 `ids` 为准）；`ids` 数量 ≤ `ARCHIVE_MAX_IDS_PER_REQUEST`，超出 → 400 并提示改用筛选。
- **可回导性校验（B1）**：超限拒绝并返回具体原因（条目数/总字节/预计 zip 体积），`estimate` 同步返回 `importable` 与 `blocking_reasons`。
- 排序固定 `publish_time DESC, id DESC`（保证 `NNN` 稳定）。
- 响应（200）：
  ```json
  { "code": 200, "message": "success",
    "data": { "ticket": "8f3c…", "download_url": "/api/v1/admin/archives/8f3c…/",
              "expires_at": "2026-09-30T01:17:30+08:00",
              "filename": "articles-20260930-011230.zip",
              "count": 3, "bytes_estimate": 218104832 } }
  ```
- 生成过程：写入 `ARCHIVE_ROOT/exports/<uuid>.zip`（流式，`ZipFile` 直接写文件），并把 `expires_at` 记入票据表；过期/已用产物由清扫回收。
- `filename` 保持纯 ASCII（避免 RFC 5987 兼容问题）；响应加 `Cache-Control: no-store`。

### 6.3 导入两阶段（D17）

```
POST /api/v1/admin/articles/import/stage/     (multipart)
  file=<zip>
→ 200 { staged_id, dry_run: true, schema, package: {entries, bytes_uncompressed, sha256},
        totals: {...}, items: [...], limits_exceeded: [] }
→ 400 包级非法（未落任何数据）; 413 超大; 403 非 staff; 429 限流

POST /api/v1/admin/articles/import/commit/    (JSON)
  { "staged_id": "…", "strategy": "skip|update|create_new",
    "auto_create_taxonomy": true, "as_draft": false, "tolerant_media": true }
→ 200 { dry_run: false, totals: {...}, items: [...], rollback_package: {...}|null }
→ 400 staged_id 不存在/已过期/已被使用; 409 已有导入进行中
```

- 暂存内容：`ARCHIVE_ROOT/staging/<staged_id>/`（原包 + 解析索引），TTL 30 分钟；`staged_id` 绑定 owner。
- **commit 必须重新解析原包**（不使用预检时缓存的对象），保证"预检看到的就是执行看到的"。
- **原子占用**：commit 用 `ArchiveStaging.objects.filter(pk=…, consumed_at__isnull=True, expires_at__gt=now).update(consumed_at=now)` 抢占，`rowcount != 1` → 409/404；commit 期间持"使用中"租约，阻止清扫删掉正在用的暂存目录。
- 回滚包（D14/D18）：**只要 plan 里存在任何对既有记录的覆盖或文件替换就生成**（不再看全局策略字符串——D9 允许单篇 `action=update`，v3 会漏生成）；生成失败 → **中止导入**。回滚包内部写入 `"import": {"action": "update"}`，使其重导时**真的会覆盖回去**（v3 的 `auto` 会导致"全跳过、零恢复"）。
- **回滚包内容范围**：受影响文章的**完整前态**（元数据 + 封面 + 附件）；施加方式即"按 `update` 策略导入该包"。

### 6.4 报告 Schema

```json
{
  "dry_run": true,
  "schema": "myblog.archive/v1",
  "package": { "entries": 34, "bytes_uncompressed": 218104832, "sha256": "…" },
  "totals": { "total": 3, "create": 1, "update": 1, "skip": 0, "failed": 1,
              "categories_to_create": ["新分类"], "tags_to_create": ["新标签"] },
  "items": [
    { "path": "articles/001-x", "slug": "tu-er-qi-ka-pa-duo-qi-ya", "title": "土耳其卡帕多奇亚",
      "action": "update", "effective_action": "update", "target_id": 30, "final_slug": "tu-er-qi-ka-pa-duo-qi-ya",
      "warnings": ["cover.sha256 与包内文件不一致，已以包内文件为准"],
      "errors": [] },
    { "path": "articles/002-y", "slug": "bad", "title": "坏数据",
      "action": "failed", "errors": ["附件类型不在白名单: exe"] }
  ]
}
```

- `action` 与 `effective_action` 都给出（后者已应用包内 `import.action` 与全局策略）。
- 警告/错误文案均为**白名单化的固定文案**（不透传原始异常字符串，见 T12）。

### 6.5 状态码

`200` 成功（含部分条目失败，看报告）｜`400` 包级非法（格式/安全/校验）｜`403` 非 staff｜`404` 票据/暂存不存在｜`409` 并发导入冲突 或 暂存已被 commit 过｜`410` 票据已用过｜`413` 超体积｜`429` 限流｜`503` 锁/缓存不可用（fail-closed）。

**票据语义（P1-A，能力 URL）**：
- `GET /admin/archives/{ticket}/` 为 `auth=None`，**不做 owner 绑定**：拿到 URL 即能下载。缓解手段：TTL 300s、单次使用、nginx `access_log off`、`Referrer-Policy: no-referrer`。
- **占用时机 = 流开始之前**（`UPDATE … WHERE used_at IS NULL` 原子占用，`rowcount=1` 才算拿到）→ 第二次访问一律 `410`；下载中断也视为已消耗，可调 `POST /admin/archives/{ticket}/reissue/`（Staff）重签。
- 票据行与磁盘文件必须一致：清扫时**先删文件再删行**，并对"有行无文件""有文件无行"两种情况分别记日志并可安全重建。

---

## 7. 数据模型变更

### 7.1 新增两张表与两个字段（迁移）

**`Article` 新增两列（D24）**：

| 字段 | 说明 |
|---|---|
| `cover_image_sha256` | 当前落盘封面文件的 SHA-256（`CharField(64, blank=True)`） |
| `file_sha256` | 当前落盘附件文件的 SHA-256（`CharField(64, blank=True)`） |

> 同时补齐现有上传/更新接口对这两列的写入（否则新上传的文章哈希为空，幂等判定会退化为"总是替换"）。

**`ArchiveTicket`**：一次性下载票据。

| 字段 | 说明 |
|---|---|
| `id` | UUID（即 URL 里的 `ticket`） |
| `user` | FK → User（校验 owner） |
| `kind` | `export` / `rollback` |
| `path` | `ARCHIVE_ROOT` 内的相对路径 |
| `filename` | 下载文件名（ASCII） |
| `bytes` | 体积 |
| `expires_at` / `used_at` | TTL 与单次使用标记 |

**`ArchiveStaging`**：暂存的导入包。

| 字段 | 说明 |
|---|---|
| `id` | UUID（即 `staged_id`） |
| `user` | FK → User |
| `dir` | `ARCHIVE_ROOT/staging/<id>/` 相对路径 |
| `sha256` / `bytes` / `entries` | 包指纹与规模 |
| `created_at` / `expires_at` / `consumed_at` | 生命周期 |

### 7.2 不再需要像素指纹

幂等依据改为 `*_sha256` 列（§4.6），**不再**在比较时解码既有文件。

---

## 8. 部署与运维变更

### 8.1 `docker-compose.yml`（D16）

```yaml
services:
  app:
    environment:
      - REDIS_URL=redis://redis:6379/0
      - ARCHIVE_ROOT=/app/private_archives
      - FILE_UPLOAD_TEMP_DIR=/app/tmp
    volumes:
      - staticfiles:/app/staticfiles
      - media:/app/media
      - ./db_data:/app/db_data
      - archives:/app/private_archives      # 新增（不对外服务）
      - apptmp:/app/tmp                     # 新增（上传暂存）
  redis:
    image: redis:7-alpine
    command: ["redis-server", "--save", "", "--appendonly", "no"]   # 仅作缓存/锁，不持久化
volumes:
  staticfiles:
  media:
  archives:      # 新增
  apptmp:        # 新增
```

> 必须在 `config/settings/base.py` 补上 `os.environ` 读取（当前 base.py **没有任何 os.environ**，否则这两条 env 是**惰性的**、空间预检会看错文件系统）。

> Redis 仅用于缓存/锁/票据辅助（票据与暂存本身落 DB），因此关闭持久化是安全的。
> 若 Redis 不可用：导入锁与限流**fail-closed**（返回 503），不静默降级。

### 8.2 gunicorn

```
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000",
     "--worker-class", "gthread", "--workers", "3", "--threads", "4",
     "--timeout", "120", "--graceful-timeout", "30"]
```

依据：默认 `workers=1 timeout=30`，单 worker 时一次归档请求会阻塞**全部** `/api/`（nginx 默认 `proxy_read_timeout 60s` → 全站 504）。`gthread` + 多 worker 同时解决阻塞与并发；这也正是必须引入 Redis 的原因（多 worker 下缓存不再共享）。

### 8.3 nginx

```nginx
# 0) 共享内存区：本文件是 conf.d 片段（位于 http{} 内），zone 声明放文件顶部即可（已实测 nginx -t 通过）
limit_req_zone  $binary_remote_addr zone=archive:10m rate=1r/s;
limit_conn_zone $binary_remote_addr zone=archive_conn:10m;

# 1a) 导出：生成可能很慢，必须单独放大超时，否则 60s 默认值会 504 并留下孤儿产物
location /api/v1/admin/articles/export/ {
    limit_req  zone=archive burst=5 nodelay;
    proxy_pass http://app:8000;
    proxy_set_header Host $http_host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 900s;
    proxy_send_timeout 900s;
}

# 1b) 导入：放大体积与超时；proxy_set_header 必须逐条重复（不从兄弟 location 继承）
location /api/v1/admin/articles/import/ {
    client_max_body_size 1g;
    client_body_timeout 300s;
    limit_req  zone=archive burst=5 nodelay;
    limit_conn archive_conn 2;
    proxy_pass http://app:8000;
    proxy_set_header Host $http_host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_request_buffering on;      # 保留缓冲：不要把客户端上传速度绑到 worker 预算
    proxy_read_timeout 900s;
    proxy_send_timeout 900s;
}

# 2) 票据下载：不进 access log，票据在路径里
location ~ ^/api/v1/admin/archives/(?<ticket>[0-9a-f-]{36})/$ {
    access_log off;
    proxy_pass http://app:8000;
    proxy_set_header Host $http_host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 900s;
    proxy_send_timeout 900s;
    add_header Referrer-Policy "no-referrer" always;
}

# 3) /media/ 全站加 nosniff；html/htm 兜底强制下载（捕获式正则 + $1，alias 不会被继承）
location /media/ {
    alias /media/;
    expires 7d;
    add_header Cache-Control "public";
    add_header X-Content-Type-Options "nosniff" always;
}
location ~* ^/media/files/(.+\.(html?|xhtml))$ {
    alias /media/files/$1;
    add_header Content-Disposition "attachment" always;
    add_header X-Content-Type-Options "nosniff" always;
}
```

要点（均为红队实测结论）：
- **zone 语法**：`limit_req zone=archive …`（速率写在 `limit_req_zone` 里）；写成 `zone=archive:1r/s` 会 `[emerg] zero size shared memory zone`，漏声明 `limit_conn_zone` 会另报 `[emerg]`。
- 正则 location 优先于前缀 location，因此 html 规则会生效；**但不能写成 glob**（`*.html?` 不匹配任何路径），也**必须带 `alias …/$1`**，否则 404/301。
- 大小写用 `~*`（Django 侧扩展名校验是小写不敏感的，`.HTML` 能通过白名单）。
- `add_header` 在 location 内**覆盖**而非追加，所以在 html location 里要重复写 `nosniff`；对下载 location 加 `add_header Referrer-Policy "no-referrer" always;`。
- 归档路径与普通 `/api/` 分离：其余接口继续受 60m 上限保护。
- `gzip_types` 不含 `application/zip`，无需改动。
- **下载 location 建议**：`proxy_buffering off; proxy_max_temp_file_size 0;`（避免 1GB 响应在 nginx 侧再落一份盘）。

### 8.4 Django settings

- 新增 §5.2 的 `ARCHIVE_*`；`ARCHIVE_ROOT` / `FILE_UPLOAD_TEMP_DIR` 均**从环境变量读**（`os.environ.get`），不再是裸字面量。
- SQLite：`OPTIONS = {'timeout': 20}`（缓解 `database is locked`）；是否开 WAL 另行评估（会多出 `-wal`/`-shm` 文件）。
- `prod.py`：若 `REDIS_URL` 未设置，启动时**告警**（锁/票据/既有登录限流都需跨进程共享缓存）。
- **空间预检**：`shutil.disk_usage()` 分别检查 `FILE_UPLOAD_TEMP_DIR`、`ARCHIVE_ROOT`、`MEDIA_ROOT`；阈值 = 预计峰值的 1.5 倍，不足 → 直接 `400`（提示而非默默写到一半）。
- **既有功能加固（M11）**：`users/api.py` 的登录限流缓存访问加 `try/except`（Redis 抖动时不能把 `/login/` 变成 500）；`common/exceptions.py` 的 500 处理改为通用文案 + 服务端 `logger.exception`。

### 8.5 启动与清扫

`docker/entrypoint.sh` **在现有 `migrate` 之前插入**（不要替换整份脚本，否则会丢掉 `collectstatic`）：

```sh
# 注意：/bin/sh 在 python:3.12-slim 上是 dash，不支持 a/{b,c} 花括号展开
mkdir -p /app/tmp /app/private_archives/staging /app/private_archives/exports /app/private_archives/rollbacks
python manage.py purge_archives    # 新增管理命令：按 TTL/mtime + DB 行双条件清扫
```

新增 `purge_archives` 管理命令（需先建 `articles/management/commands/` 目录树）：
- 删过期 `staging/*`、`exports/*`、`rollbacks/*`（**先删文件再删行**），并 GC 掉过期的 `ArchiveTicket`/`ArchiveStaging` 行（v3 只清文件不清行）；
- 跳过带"使用中租约"的暂存目录；
- 在**每次归档请求前**做一次轻量清扫，并额外提供独立定时调用（`cron`/`docker exec`），因为清扫不能只依赖请求触发。

理由：gunicorn 超时杀进程走 SIGABRT/SIGKILL，`finally` 清理**不会执行**；LocMem 也没有后台过期。

### 8.6 容量

峰值（按 1GB 包重算）≈
| 环节 | 位置 | 上限 |
|---|---|---|
| nginx 请求缓冲 | 容器 overlay `client_body_temp` | ~1GB（可用 `client_body_temp_path` 改到挂载卷） |
| Django 上传暂存 | `FILE_UPLOAD_TEMP_DIR`（apptmp） | ~1GB |
| 暂存副本（保留 30 分钟） | `ARCHIVE_ROOT/staging` | =包体（≤1GB） |
| 最终 media | `MEDIA_ROOT`（media 卷） | ≤50MB/篇 |
| 回滚包 | `ARCHIVE_ROOT/rollbacks` | ≤包体 |
| 导出产物 | `ARCHIVE_ROOT/exports` | ≤包体 |

> 注：设计是**流式读取**（`zf.open()` + 分块），**不存在**"解压产物≤500MB"这一步（v3 算错了）。
> 部署前确认 `apptmp`、`archives`、`media` 三个卷 + 容器 overlay 各有余量（建议 ≥2GB）；并把 nginx `client_body_temp_path` 指向挂载卷。

---

## 9. 前端交互（`/administrator/articles`）

**导出**
1. 表格加多选列（含全选）；移动端卡片加勾选框。
2. 工具栏：`导出所选 (3)`、`导出全部（按当前筛选）`；点击先调 `estimate`，确认框显示"共 N 篇 / 约 X MB"，确认后调 `export` 拿 `download_url`，用 `window.location.assign(download_url)` 触发**浏览器原生下载**（票据在路径里，不需要 Bearer 头，也不占浏览器内存）。
3. 无选中/列表为空时按钮禁用。

**导入**
1. `导入` 按钮 → 对话框：
   - 拖拽/选择 `.zip`；先用 `/import/limits/` 做**客户端预检**（体积、类型），不通过直接提示，避免白传 1GB。
   - 选项：策略（跳过已存在 / 覆盖更新 / 导入为新文章）、自动创建分类与标签、全部以草稿导入、媒体缺失时按角色回退。
   - `预检` → 用 `XMLHttpRequest`（**不能用 `$fetch`**，它拿不到上传进度）上传到 `/import/stage/`，显示进度条与逐篇报告表格（动作标签 + 警告/错误）。
   - 有 `errors` 的条目会列出，但不阻断其余条目；包级错误则禁用"确认导入"。
2. `确认导入` → `POST /import/commit/`（只传 `staged_id`，**不重传文件**）→ 结果摘要 + 明细 + 回滚包下载入口（若有）→ 刷新列表。
3. 常见失败给出可读引导：413 → 提示调整 nginx/上限；429 → 稍后重试；409 → 已有导入在进行。

**其它**
- `useApi.ts` 需要新增 `uploadWithProgress()`（XHR）与 `downloadByUrl()`（`location.assign`）两个小工具。

---

## 10. 边界与异常用例

**包级**：非 zip / 截断 zip／加密 zip／0 条目／只有 manifest／条目数超限／总解压超限／单文件超限／压缩比超限／路径超长／深度超限／重复条目名（含大小写与 NFC 变体）／含 `..` 或绝对路径或软链／磁盘空间不足／包体超 1GB。

**条目级**：`article.json` 缺失或非法 JSON（含 BOM、GBK、尾逗号）／非对象（数组/标量）／缺必填字段／`title` 超长／`slug` 非法或为空／`publish_time` 无偏移量或非法／`is_published` 非布尔／`author` 未知／`category` 引用不存在且已超创建上限／`tags` 超上限／声明媒体缺失／同角色多候选／封面格式与扩展名不符／封面像素超限／附件扩展名非白名单／包内 slug 重复。

**交互级**：预检后不确认直接关闭／`staged_id` 过期／同一 `staged_id` 重复 commit／两用户并发导入／导入中进程被杀。

**回归**：连续导入两次的幂等；导出→导入→再导出的语义一致性；既有 141 个测试不回归（其中 1 个需按 D19 反转，见 §15）。

---

## 11. 测试计划

| 层 | 内容 |
|---|---|
| 归档核心（纯函数） | 打包结构、manifest/article 生成、条目归一化与去重、上限判定（用 `override_settings` 把上限调到极小值来覆盖每条 400 路径） |
| 导出 | 单个/多个/按筛选/`ids` 超限/空结果/缺媒体文件时写 manifest warning/`estimate` 数值/排序含 `-id` 兜底 |
| 导入 | 三种策略 × (命中/未命中)；`MISSING` 哨兵（缺键不改、显式 null 清空）；update 不碰 `views`/`author`/时间戳（**并发 +1 场景要有专门用例**）；严格布尔；slug 校验；分类标签自动创建与超限；tolerant 回退的单候选/多候选；作者回退；as_draft 开关 |
| 幂等 | 同包 `skip` ×2、`update` ×2、`create_new` ×2 的结果与文件数 |
| 安全 | 恶意 zip fixture 生成器（`zipfile.ZipInfo` 可写入 `../`）：Zip Slip、炸弹（含**谎报 `file_size`**）、加密、重复名、大小写变体、polyglot 图片、超长字段、`html` 附件被拒 |
| 票据/暂存 | 单次使用、过期、跨用户访问、`auth=None` 下的鉴权路径、`used_at` 语义 |
| 两阶段一致性 | dry-run 与 commit 的报告条目逐个相等（同一 planner） |
| 回归 | 全量 `pytest`；D19 连带用例 |
| 手工（无法 CI） | nginx 清单：`client_max_body_size` 生效、413 行为、`proxy_read_timeout` 下长导出不断流、html 强制下载头、access log 不含票据、`nosniff` 头；Redis 断开时 fail-closed 行为 |

---

## 12. 实施阶段与改动文件

| 阶段 | 内容 | 主要改动 |
|---|---|---|
| **P0** | 格式与基础设施：`ARCHIVE_*` settings（含 env 读取）、`ARCHIVE_ROOT`、`StaffJWTAuth`、`ArchiveTicket`/`ArchiveStaging` 迁移、`Article.*_sha256` 迁移、`common/exceptions.py` 通用 500、`articles/management/commands/purge_archives.py`、`tests/test_archive_routing.py` | `config/settings/base.py`、`config/settings/prod.py`、`common/exceptions.py`、`users/authentication.py`、`articles/models.py`(新表/新列)、新 `articles/archive/` 包、`articles/management/` |
| **P1** | 导出 + 票据下载 + estimate | `articles/api.py`、`articles/archive/export.py`、`tests/test_export_articles.py` |
| **P2** | 导入：staging、planner、执行器、报告、回滚包 | `articles/api.py`、`articles/archive/{validate,planner,importer}.py`、`tests/test_import_*.py`、`tests/test_archive_security.py` |
| **P3** | 部署：compose(redis/卷)、Dockerfile CMD、nginx、entrypoint、`.env.example` | `docker-compose.yml`、`Dockerfile`、`docker/nginx/nginx.conf`、`docker/entrypoint.sh` |
| **P4** | 前端 | `front/pages/administrator/articles/index.vue`、`front/composables/useApi.ts`、`front/types/api.ts` |
| **P5** | 文档 | `DESIGN.md`(5.2 + 新 5.3.4)、`AGENTS.md`、`TEST.md`、`README.md` |
| **独立小改动** | D19 白名单收紧（与归档功能解耦，可先行） | `articles/api.py`、`front/components/admin/ArticleForm.vue`、`DESIGN.md`×3、`AGENTS.md`、反转 `tests/test_create_article.py::test_adm_008b_html_attachment` |

> 代码布局：`articles/archive/` 拆为 `errors.py`（异常与错误码）、`limits.py`（**导出/导入共用**的上限与空间预检）、`format.py`（格式常量与 JSON 序列化）、`validate.py`（包级与条目级校验）、`planner.py`（匹配与动作决策，两阶段共用）、`importer.py`（执行与补偿）、`export.py`（打包与回调包）、`locks.py`（Redis 锁与最小间隔）、`staging.py`（暂存与票据生命周期）。避免单文件超 600 行。
>
> **实施顺序建议**：P0 →（导出 + 票据 + 锁 + 核心校验）→（planner/importer/回滚）→ P3 部署 → P4 前端 → P5 文档。前两个阶段应带完整测试才能进入下一阶段。

---

## 13. 残留风险（无法根除，只能缓解）

| 风险 | 说明 | 缓解 |
|---|---|---|
| 进程被杀留下半成品 | SIGKILL 时 `finally` 不执行 | 最短临界区 + `purge_archives` 启动/请求前清扫 |
| 长传输被超时截断 | 慢客户端 + 代理超时 | 保留 nginx 请求缓冲；`proxy_read_timeout 900s`；票据可重新签发 |
| `update` 覆盖不可逆 | 旧内容随旧文件被删 | 回滚包（唯一防线）+ UI 强提示 |
| 附件类型本身可承载脚本 | PDF JS 等（`pdf/doc/docx` 亦然） | 白名单 + 强制下载（仅 html 类）+ `nosniff` + 仅管理员可导入 |
| 大包的内存/磁盘峰值 | 与包体成正比 | 流式 + 上限 + 空间预检 + 拒绝超限（无异步队列） |
| zip 编码差异（GBK/CP437） | 不同工具写 zip 方式不同 | 目录/媒体名全 ASCII + 递归发现 + JSON 按 `utf-8-sig`→GBK 回退 |
| **不是完整备份** | views/时间戳不恢复 | 明确命名"回滚包/内容导出"，README 与 DESIGN 写明边界 |
| Redis 单点 | 锁/票据/限流依赖它 | fail-closed（503）而非静默降级 + 监控告警；锁必须带 TTL（SIGKILL 后靠 TTL 自解）+ 人工解锁入口 |
| 票据是能力 URL | 拿到 URL 即能下（P1-A 的已知取舍） | TTL 300s + 单次 + `access_log off` + `no-referrer`；不把票据 URL 放进任何会被写入日志的地方 |
| 回滚包也需人手施加 | 它不是自动回滚，且本身得能导回（D23 的遗留扩展名通道因此必要） | 文档写清流程；端到端回滚测试必须存在 |
| 清扫只靠触发 | 无请求就不扫 | 除请求前轻量清扫外，另提供独立定时调用入口 |
| nginx 行为无法 CI 覆盖 | pytest 不经过 nginx | 维护手工清单（§11），部署后逐条验证 |

---

## 14. 附录：红队评审 → 修正映射

第三方独立评审（安全 / 数据 / 运维，互不共享上下文）共 32 条，全部已合并：

| 编号 | 主题 | 归入 |
|---|---|---|
| RT-01 / RT-11 | 产物落 `MEDIA_ROOT` 被匿名下载、票据进日志 | §5.1 T10/T11、§8.1/§8.3 |
| RT-02 | 无 `is_staff` 校验 | §5.1 T8、P0 |
| RT-03 / RT-17 | LocMem 缓存导致锁/票据失效；单 worker 阻塞整站；过期产物无人清 | D16、§8.1/§8.2/§8.5 |
| RT-04 | 鉴权晚于请求体读取 | §5.1 T7、§8.3 |
| RT-05 / RT-06 / RT-07 / RT-08 | update 语义（views 回退、author 改写、缺键置空、无字段校验） | §4.2 |
| RT-09 | sha256 比对对象错误 | §4.6 |
| RT-10 | nginx html 规则形态错误/大小写/DEBUG 直出 | §8.3 |
| RT-12 | `<a href>` 带不上 JWT | §6.1（`auth=None` + 票据） |
| RT-13 | 信任 `file_size` / `zf.read()` | §5.1 T2 |
| RT-14 / RT-16 | 重复上传 1GB、进度条、空间预检看错文件系统 | D17、§8.4、§9 |
| RT-15 | `proxy_request_buffering off` 是错的 | §8.3（改为 on） |
| RT-18 | `create_new` 无限复制 | §4.1、§4.8 |
| RT-19 | tolerant 回退不确定 | §4.6（仅单候选） |
| RT-20 | 重复条目名最后一条生效 | §2.1、§5.1 T5 |
| RT-21 | 包内文件名污染存储路径 | §5.1 T9、§4.6 |
| RT-22 | 异常信息泄露 | §5.1 T12 |
| RT-23 | taxonomy 上限与改名语义 | §4.3 |
| RT-24 | `is_published` 非布尔 | §4.2 |
| RT-25 | "备份"名不副实 | D18、§0、§13 |
| RT-26 | author 冒充 | §4.4 |
| RT-27 | slug 未校验 → 包名可含 `..` | §2.2、§4.2 |
| RT-28 | Pillow polyglot | §4.6（重编码 + format 校验） |
| RT-29 | naive 时间 | §4.5 |
| RT-30 | 导出序号不确定 | §6.2 |
| RT-31 | 两阶段逻辑分叉 | §4.9 |
| RT-32 | nginx 行为无法 CI | §11 手工清单 + §8.3 已实测修正 |

### 14.2 第二轮（逐条闭合审计 + 攻击 v3 自身）新增问题

| 编号 | 主题 | 归入 |
|---|---|---|
| R2-01 | 导出上限 1000 与导入上限 500 条目/500MB 矛盾 → 约 166 篇即不可回导 | §6.2、§5.2 注 |
| R2-02 | 回滚包不可施加（`action: auto` 导致全跳过）；触发条件绑全局策略（单篇 override 会绕过） | §6.3、§4.1 |
| R2-03 | 票据 `auth=None` + "绑定 owner" 自相矛盾 | P1-A、§6.5 |
| R2-04 | SQLite 上 `select_for_update` 是静默空操作（实测 `has_select_for_update=False`） | T14、§4 |
| R2-05 | nginx `limit_req zone=archive:1r/s` 实测 `[emerg]`；漏 `limit_conn_zone`；`/export/` 缺长超时 | §8.3 |
| R2-06 | entrypoint 花括号在 dash 下不展开 | §8.5 |
| R2-07 | `as_draft` × `update` 会静默下架已发布文章 | D22、§4.2 |
| R2-08 | `exif_transpose` 缺失 → 封面往返后转向 | §4.6 步骤 5 |
| R2-09 | 像素指纹对 JPEG 不成立、对 `mode='P'` 不正确 | D24、§4.6/§7 |
| R2-10 | 路由遮蔽断言错误（实测 `resolve()` → `article_id='export'`） | §6.1 |
| R2-11 | 票据/暂存缺原子占用、行不 GC、清扫可能在 commit 中删掉暂存目录、无重签端点 | §6.3/§6.5/§8.5 |
| R2-12 | 容量算式漏算 nginx 临时与暂存副本，且算了不存在的"解压产物" | §8.6 |
| R2-13 | 环境变量注入但 `base.py` 无 `os.environ` → 惰性 | §8.1/§8.4 |
| R2-14 | 空间预检无 API/阈值/中止行为 | §8.4 |
| R2-15 | 报告无法区分 skip 原因 | §6.4（加 `skip_reason`） |
| R2-16 | Redis 抖动会让既有 `/login/` 变 500 | §8.4 M11 |
| R2-17 | 媒体 `file` 解析基准未定义；嵌套 `article.json` 会重复发现同一 slug | §2.1/§2.5 |
| R2-18 | D19 造成往返不对称（存量 `.html` 能导出但导不回，含回滚包） | D23 |

---

## 15. 影响既有功能的连带变更（必须同步，勿遗漏）

**D19（附件白名单去掉 `html`）会改变既有接口行为**：

| 位置 | 现状 | 改为 |
|---|---|---|
| `articles/api.py:41` | `ATTACHMENT_EXTENSIONS = {'pdf','doc','docx','html'}` | `{'pdf','doc','docx'}` |
| `articles/api.py:69` | 错误文案 `附件仅支持 PDF/Word/HTML 格式` | `附件仅支持 PDF/Word 格式` |
| `tests/test_create_article.py:147` | `test_adm_008b_html_attachment` **断言 `.html` 可上传成功** | **反转**为断言 400（并保留"白名单外扩展名被拒"的语义） |
| `front/components/admin/ArticleForm.vue:156` | 文案 `附件（PDF/Word/HTML ≤50MB）` | `附件（PDF/Word ≤50MB）` |
| `front/components/admin/ArticleForm.vue:160` | `:accept=".pdf,.doc,.docx,.html"` | `:accept=".pdf,.doc,.docx"` |
| `DESIGN.md:511,518,704` | 三处写 PDF/DOCX/HTML | 改为 PDF/DOCX |
| `AGENTS.md:36` | `附件 PDF/Word/HTML <=50MB` | 改为 PDF/Word |

> `ArticleForm.vue:108` 的"封面与附件合计不能超过 60MB"客户端校验**保留**——它对应普通 `/api/` 路径的 nginx 60m 上限，与归档路径的 1g 上限互不影响。
