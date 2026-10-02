# my_blog

基于 Django 的个人博客项目。

## 项目结构

- 系统设计与接口文档：参见 [DESIGN.md](./DESIGN.md)
- 开发规范与常用命令：参见 [AGENTS.md](./AGENTS.md)

## 本地开发（uv）

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

用于登录 Django Admin 后台和调用管理接口，按交互提示输入用户名、邮箱、密码即可（推荐与后文 curl 示例一致：用户名 `admin`，密码 `admin12345`）：

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

首次启动会自动创建默认分类（`默认分类`）与默认标签（`默认标签`），创建文章时若未填分类/标签将自动挂载。

文章以 **Markdown 正文**为主（封面必填、附件可选）：正文在后台用 Markdown 编写、可「插入图片」（服务端会压成 WebP、最长边 1920 后落盘）与「预览」（走服务端渲染+消毒，与线上一致）。正文为空的历史文章会自动回退为「附件下载」入口。未引用的插图可用 `uv run python manage.py purge_inline_images --delete` 清理（默认只报告）。

## 前端本地开发（Nuxt）

前端位于 [`front/`](./front/) 目录（Nuxt 3 + Vue 3 + Element Plus）。

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

- **开发环境**：Nuxt dev server 通过 `nitro.devProxy` 自动代理 `/api/`、`/media/`、`/admin/` 到本地 Django（`http://127.0.0.1:8000`），无需 nginx。需先启动 Django 开发服务器（见上文「本地开发（uv）」），浏览器访问 `http://localhost:5173` 即可联调。
- **生产环境**：nginx（`:18888`）代理 `/api/`、`/media/`、`/admin/` 到 Django，前端经同源相对路径访问。

## 代码检查（Ruff + MyPy）

```bash
uv run ruff check .
uv run mypy config articles common users
```

## 接口手动测试

启动开发服务器：

```bash
uv run python manage.py runserver
```

### 方式一：Swagger 文档（最简单）

打开 `http://127.0.0.1:8000/api/v1/docs`，找到 `POST /api/v1/login/` → 点击 `Try it out` → 请求体填写登录凭据后执行。

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

刷新令牌：

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

密码错误返回 HTTP 401。之后用 `Authorization: Bearer <access>` 访问受保护的 `/api/v1/me/` 即可获取用户信息。

## 生产环境（Docker）

### 一键脚本（推荐）

`scripts/blog.sh` 把构建 / 启动 / 体检 / 导出 / 导入固化为子命令，已内建本项目实测踩过的坑（podman-compose 不会因镜像变更重建容器、SELinux 需 `:z`、`.env` 必填项校验、等就绪而非 `sleep`）：

**脚本会自动识别容器工具链**（`docker compose` v2 → `docker-compose` v1 → `podman-compose` → `podman compose`；docker 需 daemon 可达），也可用 `BLOG_ENGINE=docker|podman` 强制指定；两种引擎的容器命名、镜像名与 `save` 参数差异都由脚本内部处理。

```bash
scripts/blog.sh preflight           # 环境体检（podman/compose/架构/SELinux/端口/磁盘/配置语法）
scripts/blog.sh up --build          # 构建 → 重建容器 → 等待就绪 → 健康检查
scripts/blog.sh status              # 容器/镜像/端口/健康/归档产物/磁盘 一览
scripts/blog.sh check --front       # 质量门禁（ruff/mypy/pytest/迁移/配置语法/vue-tsc）
scripts/blog.sh logs app -f         # 看日志（app|nginx|front|redis）
scripts/blog.sh down                # 停止（保留数据卷与 db_data/）

scripts/blog.sh export              # 导出离线镜像包（默认名带时间戳，省略 --out）
scripts/blog.sh import --in 包.tar   # 目标机离线部署（校验 → load → 重建 → 健康检查）
scripts/blog.sh seed-media          # 把本机 media/ 同步进媒体卷（数据迁移用）
scripts/blog.sh seed-demo           # 生成并导入 30 篇演示游记（含 Markdown 正文与压缩插图）
scripts/blog.sh purge               # 清归档过期产物 + 悬空镜像
```

完整参数：`scripts/blog.sh help`；离线部署细节见 [`docs/OFFLINE_IMAGE_DEPLOY.md`](./docs/OFFLINE_IMAGE_DEPLOY.md)。

> 下面为手动步骤（用 docker compose 也可以用同样顺序；脚本会自动识别引擎，无需改任何配置）。

```bash
DJANGO_ENV=prod docker compose up --build
```

### 启动与停止

**前置检查**（确认本机 docker 可用）：

```bash
docker version && docker compose version
```

**构建并后台启动全部服务**（app + nginx）：

```bash
docker compose up --build -d
```

**查看启动状态**（等 app 变 running，migrate+collectstatic 需几秒）：

```bash
docker compose ps
```

**只测 app 服务**（nginx 仍会连带拉起，app 无其他依赖）：

```bash
docker compose up --build -d app
docker compose ps
```

**看日志**（确认 migrate/collectstatic/gunicorn 正常）：

```bash
docker compose logs -f app
```

**创建管理员**（首次部署时执行；数据库已持久化到宿主机 `db_data/`，之后容器销毁重建无需再创建）：

```bash
docker compose exec app python manage.py createsuperuser
```

登录拿 token 后即可测试 `GET /api/v1/me/`（`Authorization: Bearer <access>`）、`GET /api/v1/articles/` 等接口（经 nginx 入口 `http://<IP>/api/v1/...`）。

**停止与清理**：

```bash
# 停止并删除容器（保留数据：db_data/ 与 named volumes media/staticfiles）
docker compose down

# 彻底清理（慎用）：删除 named volumes（media/staticfiles）；注意 bind mount 的 db_data/ 不会被 -v 删除，需 rm -rf db_data。
docker compose down -v

# 重新构建（Dockerfile/依赖变更后）
docker compose build
```

已部署宿主机上遗留的 postgres_data 卷不会被自动删除，可手动 `docker volume rm <compose项目名>_postgres_data` 清理（卷名前缀取决于 compose 项目名，可用 `docker volume ls | grep postgres` 确认）。

### 通过 Docker + Nginx 访问

docker compose 部署后，入口统一为 `http://<IP>:18888/`（nginx:18888，映射宿主机 18888 端口），静态文件与所有接口均经 nginx 提供：

- Swagger 文档：`http://192.168.31.96:18888/api/v1/docs`
- Django admin：`http://192.168.31.96:18888/admin/`

应用容器自身的 8000 端口不再对外暴露，无法直接访问 `:8000`。

部署注意事项：

- 内网穿透客户端指向 `127.0.0.1:18888`
- `.env` 的 `DJANGO_ALLOWED_HOSTS` 需包含真实内网 IP `192.168.31.96` 并追加穿透域名，修改后必须 `docker compose up -d app` 重建容器才生效
- 宿主机防火墙放行 18888/tcp（含 docker bridge → 宿主机回环路径，供 SSR 访问）

### 数据持久化

- 数据库：`db.sqlite3` 经 bind mount 存宿主机 `db_data/` 目录（容器销毁重建不丢，下次启动自动续用）；本地开发首次 migrate 前需先 `mkdir -p db_data`
- 上传文件：`media/` 经 named volume `media` 持久化（app 与 nginx 共享）
- 静态文件：`staticfiles/` 经 named volume `staticfiles` 持久化（collectstatic 产物，可重建）
- `docker compose down` 不删数据；只有 `rm -rf db_data` 才删除数据库
