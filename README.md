# my_blog

基于 Django 的个人博客项目。

## 项目结构

- 系统设计与接口文档：参见 [DESIGN.md](./DESIGN.md)
- 开发规范与常用命令：参见 [AGENTS.md](./AGENTS.md)

## 本地开发（uv）

```bash
uv sync
uv run python manage.py migrate
uv run python manage.py runserver
```

局域网内其他设备访问时，需监听 `0.0.0.0`（dev 环境 `ALLOWED_HOSTS` 已放开为 `*`，CORS 也已全面放开）：

```bash
uv run python manage.py runserver 0.0.0.0:8000
```

然后通过本机局域网 IP 访问，如 `http://192.168.x.x:8000/api/v1/docs`。

首次启动会自动创建默认分类（`默认分类`）与默认标签（`默认标签`），创建文章时若未填分类/标签将自动挂载。

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

```bash
DJANGO_ENV=prod docker compose up --build
```
