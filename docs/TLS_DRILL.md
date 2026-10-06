# TLS / HTTPS 启用演练（OPS-05）

**用途**：本项目默认是「纯 HTTP + nginx 监听 `0.0.0.0:18888`」的内网部署，`DJANGO_USE_TLS` 默认关。
TLS 启用路径（`DJANGO_USE_TLS` → `SECURE_SSL_REDIRECT` / 安全 Cookie / `SECURE_PROXY_SSL_HEADER` → HSTS）
此前从未实测验证，本文给出**一次可复现的演练步骤**与验证清单。

> 适用范围：反向代理（nginx）终止 TLS、Django 跑在 HTTP 之后的标准形态。当前 `nginx.conf` 只监听明文
> `18888`，TLS 需要新增加密 server 块或把证书终止放到更外层（如宿主机 nginx / 负载均衡）。

---

## 一、演练前确认

- 有一个域名（示例 `blog.example.com`）解析到目标机；只有 IP 也能自签/内网 CA 证书跑通流程。
- 证书 + 私钥就位（示例放 `docker/nginx/certs/`，**不要提交进仓库**）。
- 先按 `scripts/blog.sh up --build` 起一套现有 HTTP 环境，确认基线可用（`scripts/blog.sh check` 全绿）。

## 二、nginx：新增加密 server 块

在 `docker/nginx/nginx.conf` 的 `server { listen 18888; ... }` **之前**插入（保持现有明文块不动，
两者共存便于灰度；正式切换时再把明文块改为 301 跳转）：

```nginx
# HTTPS 入口：证书/私钥挂载到容器内（compose 需加只读挂载）
server {
    listen 18443 ssl;
    http2 on;
    server_name blog.example.com;

    ssl_certificate     /etc/nginx/certs/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    # 关键：告诉 Django 原始协议是 https（对应 SECURE_PROXY_SSL_HEADER）
    # 其余 location 的 proxy_set_header 与 18888 块保持一致，此处省略
    location / {
        proxy_pass http://front:3000;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;   # ← $scheme 在 443 块里为 https
    }
    # …/api/、/admin/、/media/、/static/ 等 location 从明文块整段复制，勿漏 proxy_set_header
}
```

`docker-compose.yml` 的 nginx 服务需同时暴露 `18443:18443`，并挂载证书目录（`certs:...:ro,z`）。

## 三、Django：打开安全开关

在 `.env`（compose 的 `env_file`）里设置：

```dotenv
DJANGO_USE_TLS=true
DJANGO_SECURE_HSTS_SECONDS=31536000
DJANGO_CSRF_TRUSTED_ORIGINS=https://blog.example.com
DJANGO_ALLOWED_HOSTS=blog.example.com
# REDIS_URL 保持启用（见 OPS-04）
```

改完后重建容器（`podman-compose up -d` 不会因 `.env` 变更重启，需 `down && up` 或 `blog.sh restart`）。

## 四、验证清单（逐条打勾）

| # | 断言 | 命令 / 位置 | 期望 |
| - | --- | --- | --- |
| 1 | HTTP 强制跳 HTTPS | `curl -sI http://<ip>:18888/` | `301`，`Location: https://...` |
| 2 | HTTPS 可访问 | `curl -sI https://blog.example.com/` | `200` |
| 3 | HSTS 头 | `curl -sI https://blog.example.com/ \| grep -i strict-transport` | `max-age=31536000; includeSubDomains; preload` |
| 4 | 安全 Cookie | 浏览器 DevTools → Application → Cookies（登录后） | `csrftoken` / `sessionid` 带 `Secure` |
| 5 | admin 表单可用 | `https://blog.example.com/admin/` 登录并提交 | 无 CSRF 403 |
| 6 | API 可用 | `POST /api/v1/login/` 取 JWT | `200`，响应含 token |
| 7 | 无重定向环 | 保持登录刷新多页 | 不出现 `ERR_TOO_MANY_REDIRECTS` |
| 8 | 媒体直出 | 打开任一带封面的文章 | 图片 200（`/media/` 直出，不经 Django） |

> 第 1、7 条最易踩：`SECURE_SSL_REDIRECT=True` 时若代理没传 `X-Forwarded-Proto: https`
> （或容器外还套了一层未透传的代理），Django 会一直把自己当成 HTTP → 无限 301。

## 五、回滚

1. `.env` 里 `DJANGO_USE_TLS=false`、`DJANGO_SECURE_HSTS_SECONDS=0`（HSTS 一旦下发，浏览器会缓存，
   演练阶段建议先用 `max-age=300` 短值，确认无误后再上调到 1 年）。
2. `down && up` 重建容器；删除/注释 nginx 加密 server 块。
3. 验收：明文 `http://<ip>:18888/` 恢复 200，无 301。

## 六、演练记录

- **2026-10-06 本机（Windows dev）· 配置层演练：通过。** 以 `DJANGO_ENV=prod` +
  `DJANGO_USE_TLS=true` 加载 `config.settings`，实测解析结果与预期一致：
  `SECURE_SSL_REDIRECT=True`、`SESSION_COOKIE_SECURE=True`、`CSRF_COOKIE_SECURE=True`、
  `SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO','https')`、
  `SECURE_HSTS_SECONDS=31536000`（`INCLUDE_SUBDOMAINS`/`PRELOAD` 均为 True）、
  `CSRF_TRUSTED_ORIGINS=['https://blog.example.com']`。
  （该项由 TEST-04 的 `tests/test_prod_settings.py` 固化为回归用例。）
- **容器层（nginx TLS 终止 + 真实证书）未在本机执行**：本机无 `podman`/`docker`，
  只能在装有容器工具链的部署机按本文第二/三节执行；执行后请把日期与结果补记在此处。