# 离线 / 免构建部署（使用导出的镜像）

**用途**：在无外网或拉取极慢的机器上部署本博客：不 `build`、不 `pull`，直接用导出的镜像 tar。

> 默认导出路径：`~/my_blog_images/my_blog_images_<架构>_<YYYYmmdd-HHMMSS>.tar`（时间戳到秒，同一天多次导出不会互相覆盖）。

**适用的目标机**：`linux/amd64`（x86_64），已装 `podman` + `podman-compose`。
（镜像架构必须在导出时确认：`podman image inspect localhost/my_blog_app:latest --format '{{.Architecture}}/{{.Os}}'`）

> **推荐直接用脚本**，本节的手工步骤只作为原理参考（脚本自动识别 `docker compose` 或 `podman`，不需改任何配置）：
> ```bash
> scripts/blog.sh export                        # 源机：导出（省略 --out 即写到 ~/my_blog_images/，文件名带架构+时间戳，并生成 .sha256）
> scripts/blog.sh export --out /data/pkg.tar    # 也可显式指定路径（--out 不带值时同样回落到默认名）
> scripts/blog.sh import --in <包路径>           # 目标机：校验 sha256/架构/磁盘 → load → 重建 → 健康检查
> scripts/blog.sh import                       # 省略 --in 时自动选用 ~/my_blog_images/ 下最新的包
> scripts/blog.sh seed-media                    # 若要把本机 media/ 里的封面附件一起带过去
> ```
> 脚本会做同样的校验，并额外保证：**不用 `--build`**、`down` 后再 `up`、轮询等就绪、健康检查四条路径。

---

## 一、镜像包里有什么

导出的是 compose 用到的 **4 个镜像**，一条命令打包成一个 tar：

| 镜像 | 约计大小 | 来源 |
| --- | --- | --- |
| `localhost/my_blog_app:latest` | 220 MB | 本仓库 `Dockerfile` 构建（Django + gunicorn + 依赖） |
| `localhost/my_blog_front:latest` | 179 MB | `front/Dockerfile` 构建（Nuxt SSR 产物 `.output`） |
| `docker.io/library/nginx:1.27` | 197 MB | 公共镜像（已拉取） |
| `docker.io/library/redis:7-alpine` | 39.9 MB | 公共镜像（已拉取，用于缓存/锁） |

归档包总计约 **606 MB**（4 个镜像合计 636 MB，共享层会再压一点）。

导出/导入用的 tag **必须与 compose 期望的一致**：podman-compose 会把 `build:` 服务的镜像名解析为 `localhost/my_blog_<service>`，故 tar 里的 tag 就是 `localhost/my_blog_app` / `localhost/my_blog_front`。

## 二、导出（在已构建好的源机器上）

```bash
mkdir -p ~/my_blog_images
PKG="$HOME/my_blog_images/my_blog_images_amd64_$(date +%Y%m%d-%H%M%S).tar"
podman save --format docker-archive -m -o "$PKG" \
  localhost/my_blog_app:latest \
  localhost/my_blog_front:latest \
  docker.io/library/nginx:1.27 \
  docker.io/library/redis:7-alpine
# 校验和写成 GNU 标准格式 "<hash>  <文件名>"，目标机才能直接 sha256sum -c
( cd "$(dirname "$PKG")" && sha256sum "$(basename "$PKG")" ) > "${PKG}.sha256"
```

（`scripts/blog.sh export` 就是上面这段，命名规则为 `my_blog_images_<arch>_<YYYYMMDD-HHMMSS>.tar` + 同名 `.sha256`。）

目标机校验（**必须在 tar 所在目录执行**，`-c` 按当前目录解析文件名）：

```bash
cd ~/Code/my_blog            # 或 tar 所在处
sha256sum -c my_blog_images_amd64_20261001.tar.sha256     # → "…: 成功"
```

- `--format docker-archive`：podman 与 docker 都能 `load`
- `-m`：多镜像归档（一个 tar 装 4 个镜像）
- 产物约 **606 MB**（层已按原样写入，再 gzip 收益有限：多数层本就是压缩 blob）

参考（2026-10 首次导出快照，仅用于校验传输完整性）：**606 MB / sha256 `158e2e02521f18fc473a94cdc87694c7b879b3e0f4661c4bda6530b0328c6dcf`**。重新构建后这两个值都会变。

可选：想减小传输体积再 `zstd -3 -T0 my_blog_4images_amd64.tar`（目标机解压后 `podman load`）。

## 三、导入并启动（在目标机器上）

```bash
# 1) 拷贝 tar（示例：从源机器拉取）
scp yquian@<源IP>:~/my_blog_images/my_blog_4images_amd64.tar /tmp/

# 2) 导入镜像（会还原 4 个 tag）
podman load -i /tmp/my_blog_4images_amd64.tar
podman images | grep -E 'my_blog_|nginx:1.27|redis'

# 3) 准备环境变量（compose 的 env_file 必需；.env 不入库）
cd /path/to/my_blog
cp .env.example .env          # 也可跳过：scripts/blog.sh up 会自动生成一份
#   然后改成：DJANGO_ENV=prod、DJANGO_SECRET_KEY=<随机串>、DJANGO_ALLOWED_HOSTS=<IP 或 *>

# 4) 首次需要数据库目录（compose 绑定挂载）
mkdir -p db_data

# 5) 启动 —— **不要加 --build**
podman-compose up -d

# 6) 验证
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18888/api/v1/articles/   # 期望 200
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18888/api/v1/docs        # 期望 200
```

首次启动时 `entrypoint.sh` 会自动 `migrate` + `collectstatic` + `purge_archives`，无需手工执行。

## 四、注意事项

1. **镜像内是代码快照**：`my_blog_app` / `my_blog_front` 在构建时把源码 COPY 进去了（`.dockerignore` 已排除 `db_data/`、`media/`、`private_archives/`、`.env`、`tests/`）。因此**改了代码必须重新构建 + 重新导出**，直接改宿主机源码对已加载的镜像无效。
2. **目标机是 docker 而非 podman 时**：`docker load` 也能导入（同为 docker-archive 格式）。镜像 tag 的 `localhost/` 前缀差异（podman 导出为 `localhost/my_blog_app:latest`，docker 期望 `my_blog_app:latest`）已由 `scripts/blog.sh import` **自动补标签**；手工操作时需自行 `docker tag localhost/my_blog_app:latest my_blog_app:latest`。
3. **SELinux（Fedora 等 Enforcing 发行版）**：compose 里 `./db_data` 与 `./docker/nginx/nginx.conf` 的挂载已带 `:z` / `:ro,z`，否则容器内会 `Permission denied`。
4. **磁盘需求**：镜像解包后约 640 MB，加上 tar 本体共约 1.2 GB。
5. **数据不在镜像里**：`db_data/`（SQLite）、`media/`（封面与附件）、`private_archives/`（归档产物）都是挂载卷/绑定目录。**换机器时若要带走文章数据**，需要单独拷贝 `db_data/`，以及把 `media/` 内容导入 `my_blog_media` 卷：
   ```bash
   podman volume create my_blog_media 2>/dev/null || true
   podman cp media/. my_blog_app_1:/app/media/     # 容器起来后执行
   ```
6. **`podman-compose up -d` 不会因镜像变更重建容器**（docker compose 会）：更换了 tar/镜像后要 `podman-compose down && podman-compose up -d`。`scripts/blog.sh up` / `import` 已一律走 down+up 并核对容器 `Image` ID。

---

## 五、镜像为什么能这幺小（多阶段构建）

两个自制镜像都改成了**多阶段构建**，把“只在构建期需要”的东西彻底挡在最终镜像之外：

| 镜像 | 构建阶段（被丢弃） | 运行阶段（保留） | 效果 |
| --- | --- | --- | --- |
| `my_blog_app` | `python:3.12-slim` + `apt install build-essential`（+313 MB）+ `uv` 二进制（+56 MB） | `python:3.12-slim` + `/opt/venv` + 源码 | 683 MB → **220 MB** |
| `my_blog_front` | `node:22-alpine` + `npm ci`（+754 MB，含全部 devDependencies） | `node:22-alpine` + `.output` | 959 MB → **179 MB** |

要点与副作用：

1. **依赖已全部是预编译 wheel**（Pillow / cryptography / pydantic-core 等），构建日志里没有任何源码编译，因此编译器在运行阶段完全不需要。
2. 运行阶段的 `PATH` 指向 `/opt/venv/bin`，所以 `python` / `gunicorn` 都来自该 venv；**镜像内已无 `uv` 与 `gcc`** —— 如需在容器里临时装东西，得自行 `apt-get`/`pip`。
3. Nuxt 的 `.output` 是自包含的（Nitro 把服务端依赖打进了产物），因此运行阶段不需要 `node_modules`。
4. **改了代码必须重新构建 + 重新导出 tar**：镜像内是代码快照，`COPY . .` 已经发生。
5. 自检方式（加载后可跑）：
   ```bash
   podman run --rm --entrypoint sh localhost/my_blog_app:latest -c 'cd /app && python manage.py check'
   ```
