# 开发与手工部署指南

> 本文承接从 [README](../README.md) 迁出的长流程细节：本地开发五步、前端联调、接口手工测试、
> 以及不用 `scripts/blog.sh` 时的原生 Docker 手动步骤。
> 生产部署优先使用统一入口 `scripts/blog.sh`（见 README「部署与运维」）。

---

## 一、本地开发（uv）

### 第一步：安装依赖

```bash
uv sync
```

### 第二步：准备数据库目录

SQLite 数据库文件存放在 `db_data/` 目录下（被 `.gitignore` 忽略，首次克隆需手动创建）：

**Windows（PowerShell / CMD）：**

```powershell
mkdir db_data
```

**Linux / macOS：**

```bash
mkdir -p db_data
```

### 第三步：执行数据库迁移

创建数据库表结构（首次部署或有新迁移时执行）：

```bash
uv run python manage.py migrate
```

### 第四步：创建超级管理员

用于登录 Django Admin 后台和调用管理接口，按交互提示输入用户名、邮箱、密码即可
（与下文 curl 示例一致时：用户名 `admin`，密码 `admin12345`）：

```bash
uv run python manage.py createsuperuser
```

### 第五步：启动开发服务器

```bash
uv run python manage.py runserver
```

局域网内其他设备访问时，需监听 `0.0.0.0`（dev 环境 `ALLOWED_HOSTS` 已放开为 `*`，CORS 也已全面放开）：

```bash
uv run python manage.py runserver 0.0.0.0:8000
```

然后通过本机局域网 IP 访问，如 `http://192.168.x.x:8000/api/v1/docs`。

首次创建文章时若未填分类/标签，会自动挂载默认分类（`默认分类`）与默认标签（`默认标签`），二者惰性创建、受删除保护。

文章以 **Markdown 正文**为主（封面必填、附件可选）：正文在后台用 Markdown 编写，可「插入图片」
（服务端压成 WebP、内容寻址落盘）与「预览」（服务端渲染 + 消毒，与线上一致）。正文为空的历史文章
自动回退为「附件下载」入口。未引用的插图可用 `uv run python manage.py purge_inline_images --delete` 清理（默认只报告）。

---

## 二、前端本地开发（Nuxt）

前端位于 [`front/`](../front/)（Nuxt 3 + Vue 3 + Element Plus）。

**安装依赖**：

```bash
cd front
npm install
```

**启动开发服务器**：

```bash
npm run dev
```

默认监听 `0.0.0.0:5173`，浏览器访问 `http://localhost:5173`（局域网内其他设备可通过本机局域网 IP 访问）。

**与后端对接**：

前端 API 基址为相对路径 `/api/v1/`（`front/nuxt.config.ts` 的 `runtimeConfig.public.apiBase`），生产/开发零差异：

- **开发环境**：Nuxt dev server 通过 `nitro.devProxy` 自动代理 `/api/`、`/media/` 到本地 Django
  （`http://127.0.0.1:8000`），无需 nginx。需先启动 Django 开发服务器，浏览器访问 `http://localhost:5173` 即可联调。
- **生产环境**：nginx（`:18888`）代理 `/api/`、`/media/`、`/admin/` 到 Django，前端经同源相对路径访问。

---

## 三、代码检查

```bash
uv run ruff check .
uv run mypy config articles common users
uv run pytest
```

前端（`front/`）：

```bash
cd front
npm run lint          # ESLint
npx vue-tsc --noEmit  # 类型检查
npm test              # vitest
```

一次跑完全部门禁（含迁移一致性、配置语法、文档漂移自查、shellcheck、前端三件套）：

```bash
scripts/blog.sh check
```

---

## 四、接口手工测试

启动开发服务器：

```bash
uv run python manage.py runserver
```

### 方式一：Swagger 文档（最简单）

打开 `http://127.0.0.1:8000/api/v1/docs`，找到 `POST /api/v1/login/` → `Try it out` → 填入登录凭据后执行。

### 方式二：curl

登录获取令牌：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin12345"}'
```

用返回的 `access` 令牌访问当前用户信息：

```bash
curl http://127.0.0.1:8000/api/v1/me/ -H "Authorization: Bearer <access值>"
```

刷新令牌（会同时轮换 refresh，旧 refresh 进黑名单）：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/token/refresh/ \
  -H "Content-Type: application/json" \
  -d '{"refresh": "<refresh值>"}'
```

### 方式三：Postman / Apifox 等工具

- 接口：`POST http://127.0.0.1:8000/api/v1/login/`
- 请求头：`Content-Type: application/json`
- Body：`{"username": "admin", "password": "admin12345"}`

### 预期返回

登录成功（HTTP 200）：

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "access": "eyJhbGciOiJIUzI1NiIs...",
    "refresh": "eyJhbGciOiJIUzI1NiIs..."
  }
}
```

密码错误返回 HTTP 401；同一「客户端 IP + 用户名」连续失败 5 次锁定 5 分钟（返回 429）。
参数校验失败（Pydantic 拦截）返回 **422**，响应体形如 `{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}`，不走统一信封。

---

## 五、原生 Docker 手动步骤（不使用 blog.sh 时）

```bash
DJANGO_ENV=prod docker compose up --build
```

### 前置检查

```bash
docker version && docker compose version
```

### 构建并后台启动

```bash
docker compose up --build -d
docker compose ps            # 等 app 变 running（migrate + collectstatic 需几秒）
docker compose logs -f app   # 确认 migrate/collectstatic/gunicorn 正常
```

只测 app 服务（nginx/front 会经 `depends_on` 连带拉起）：

```bash
docker compose up --build -d app
```

### 创建管理员

首次部署执行一次即可（数据库已持久化到宿主机 `db_data/`，容器销毁重建无需再建）：

```bash
docker compose exec app python manage.py createsuperuser
```

### 停止与清理

```bash
# 停止并删除容器（保留数据：db_data/ 与 named volumes media/staticfiles）
docker compose down

# 彻底清理（慎用）：删除 named volumes；bind mount 的 db_data/ 不会被 -v 删除，需 rm -rf db_data
docker compose down -v

# 重新构建（Dockerfile/依赖变更后）
docker compose build
```

> ⚠️ `podman-compose up -d` 不会因镜像变更而重建已存在的容器（只比较镜像名）。
> 改了 Dockerfile/依赖后必须 `down && up`，或检查容器 `Image` ID 是否等于 `latest`；
> `scripts/blog.sh up` 已内建该行为。

### 通过 nginx 访问

入口统一为 `http://<IP>:18888/`：`/` → Nuxt SSR，`/api/`、`/admin/` → Django，`/media/`、`/static/` → 直接由 nginx 送出。
应用容器的 8000 端口不对宿主机暴露。生产默认关闭 Swagger（`/api/v1/docs`），需要时在 `.env` 设 `ENABLE_API_DOCS=true` 后重启。

部署注意事项：

- 内网穿透客户端指向 `127.0.0.1:18888`
- `.env` 的 `DJANGO_ALLOWED_HOSTS` 需包含真实内网 IP 并追加穿透域名，修改后必须 `docker compose up -d app` 重建容器才生效
- 宿主机防火墙放行 18888/tcp（含 docker bridge → 宿主机回环路径，供 SSR 访问）

### 数据持久化

- 数据库：`db_data/db.sqlite3` 经 bind mount 存宿主机（容器销毁重建不丢）
- 上传文件：`media/` 走 named volume，app 与 nginx 共享
- 静态文件：`staticfiles/` 走 named volume（collectstatic 产物，可重建）
- 归档产物：`private_archives/` 走 named volume，**绝不位于 `MEDIA_ROOT` 下**（nginx 对 `/media/` 无鉴权）
- `docker compose down` 不删数据；只有 `rm -rf db_data` 才删除数据库

已部署宿主机上遗留的 `postgres_data` 卷不会被自动删除，可手动
`docker volume rm <compose项目名>_postgres_data` 清理（卷名前缀取决于 compose 项目名，用 `docker volume ls | grep postgres` 确认）。
