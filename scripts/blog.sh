#!/usr/bin/env bash
#
# 个人博客：部署运维一体化脚本
#
#   scripts/blog.sh <子命令> [选项]
#
# 子命令：
#   preflight            环境体检（podman/podman-compose/架构/SELinux/端口/磁盘/配置语法）
#   up [--build]         构建（可选）→ 重建容器 → 等待就绪 → 健康检查
#   down [--purge]       停止容器（--purge 连数据卷一起删，需确认）
#   restart [--build]    等价于 down + up
#   status               容器 / 镜像 / 端口 / 健康 / 归档产物 / 磁盘 一览
#   logs [服务] [-f]     查看日志（app|nginx|front|redis，默认 app）
#   check [--no-front] [--e2e]
#                        质量门禁（ruff/mypy/pytest/迁移检查/配置语法/文档漂移自查/前端 ESLint+vue-tsc；--no-front 跳过前端，
#                        --e2e 追加真实链路冒烟）
#   e2e                  端到端冒烟（对已运行的容器跑登录 → 建文章 → 导出）
#   install-hooks        启用仓库 git 钩子（pre-push 跑上面的 check，防坏代码直达远端）
#   export [--out 文件]  导出离线镜像包（4 镜像 → tar + .sha256；省略 --out 用默认名）
#   import [--in 文件]   目标机：校验 → 加载镜像 → 重建容器 → 健康检查（绝不 --build）
#   seed-media           把本机 media/ 同步进媒体卷（数据迁移用）
#   seed-demo [--count N] 生成并导入演示游记（含 Markdown 正文与压缩插图，走真实导入链路）
#   backup [--out 文件]  备份 SQLite 数据库（热备 + integrity_check；省略 --out 用默认名）
#   purge                清理归档过期产物 + 悬空镜像
#   help                 显示本帮助
#
# 说明：所有涉及"改了镜像"的操作都会强制 down + up —— podman-compose 不会因镜像变更
# 重建已存在的容器（它只比较镜像名），这是本项目实测踩过的坑。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# --------------------------------------------------------------------------- 常量
PROJECT="my_blog"
NGINX_PORT="18888"
NGINX_IMAGE="docker.io/library/nginx:1.27"
BASE_URL="http://127.0.0.1:${NGINX_PORT}"
# 以下三个由 resolve_image_names 按检测到的引擎填充（podman 用 localhost/ 前缀，docker 不加）
APP_IMAGE=""
FRONT_IMAGE=""
APP_ALT=""
FRONT_ALT=""
IMAGES=()
# 探活路径：均为生产默认可达的 200 端点（/api/v1/docs 生产默认关闭，不能用作探活）
HEALTH_PATHS=("/" "/api/v1/articles/" "/api/v1/categories/")
EXPORT_DIR_DEFAULT="${HOME}/my_blog_images"
BACKUP_DIR_DEFAULT="${HOME}/my_blog_backups"
WAIT_READY_TIMEOUT=180

# --------------------------------------------------------------------------- 输出
if [ -t 1 ]; then
  C_OK=$'\e[32m'; C_WARN=$'\e[33m'; C_ERR=$'\e[31m'; C_DIM=$'\e[2m'; C_BOLD=$'\e[1m'; C_END=$'\e[0m'
else
  C_OK=''; C_WARN=''; C_ERR=''; C_DIM=''; C_BOLD=''; C_END=''
fi
STEP_NO=0
step() { STEP_NO=$((STEP_NO + 1)); printf '%s[%d]%s %s ... ' "$C_BOLD" "$STEP_NO" "$C_END" "$1"; }
# 需要展示命令输出的步骤：标题独占一行，输出自行缩进后调用 ok
block_step() { STEP_NO=$((STEP_NO + 1)); printf '%s[%d]%s %s\n' "$C_BOLD" "$STEP_NO" "$C_END" "$1"; }
# 运行并把输出缩进展示；失败即退出
run_show() {
  local name="$1"; shift
  block_step "$name"
  if ! "$@" 2>&1 | sed 's/^/    /'; then fail "$name 未通过"; exit 1; fi
  ok
}
run_show_tail() {
  local name="$1" lines="$2"; shift 2
  block_step "$name"
  if ! "$@" 2>&1 | tail -n "$lines" | sed 's/^/    /'; then fail "$name 未通过"; exit 1; fi
  ok
}
ok()   { printf '%s[OK]%s %s\n' "$C_OK" "$C_END" "${1:-}"; }
warn() { printf '%s[WARN]%s %s\n' "$C_WARN" "$C_END" "$1"; }
fail() { printf '%s[FAIL]%s %s\n' "$C_ERR" "$C_END" "$1"; }
die()  { fail "$1"; [ "${2:-}" != "" ] && printf '  %s提示：%s%s\n' "$C_DIM" "$2" "$C_END"; exit 1; }
hint() { printf '  %s%s%s\n' "$C_DIM" "$1" "$C_END"; }
title() { printf '\n%s=== %s ===%s\n' "$C_BOLD" "$1" "$C_END"; }

# --------------------------------------------------------------------------- 基础
# --------------------------------------------------------------------------- 引擎探测
# 同时支持两套工具链，自动检测（可用 BLOG_ENGINE=docker|podman 覆盖）：
#   docker：docker compose（v2 插件）或 docker-compose（v1，需 daemon 可达）
#   podman：podman-compose 或 podman compose（转发到外部 provider）
ENGINE=""          # 容器引擎 CLI：docker | podman
COMPOSE_CMD=()     # compose 前端命令（数组）
ENGINE_SOURCE=""   # 探测来源，供 preflight 展示
PROBE_ERROR=""    # probe_engine 失败原因

_has() { command -v "$1" >/dev/null 2>&1; }

# 纯探测：设置 ENGINE/COMPOSE_CMD/ENGINE_SOURCE，失败返回 1 并把原因放 PROBE_ERROR（不退出）
probe_engine() {
  local forced="${BLOG_ENGINE:-}"
  ENGINE=""; COMPOSE_CMD=(); ENGINE_SOURCE=""; PROBE_ERROR=""

  if [ -n "$forced" ] && [ "$forced" != "docker" ] && [ "$forced" != "podman" ]; then
    PROBE_ERROR="BLOG_ENGINE 只能是 docker 或 podman（当前：${forced}）"
    return 1
  fi

  # docker：CLI 存在**且 daemon 可达**（只装了 CLI 但没启 daemon 时不应误判）
  if [ "$forced" != "podman" ] && _has docker && docker info >/dev/null 2>&1; then
    if docker compose version >/dev/null 2>&1; then
      ENGINE=docker; COMPOSE_CMD=(docker compose); ENGINE_SOURCE="docker compose（v2 插件）"
    elif _has docker-compose; then
      ENGINE=docker; COMPOSE_CMD=(docker-compose); ENGINE_SOURCE="docker-compose（v1）"
    fi
    [ -n "$ENGINE" ] && return 0
  fi

  if [ "$forced" != "docker" ] && _has podman; then
    if _has podman-compose; then
      ENGINE=podman; COMPOSE_CMD=(podman-compose); ENGINE_SOURCE="podman-compose"
    elif podman compose version >/dev/null 2>&1; then
      ENGINE=podman; COMPOSE_CMD=(podman compose); ENGINE_SOURCE="podman compose"
    fi
    [ -n "$ENGINE" ] && return 0
  fi

  if [ -n "$forced" ]; then
    PROBE_ERROR="BLOG_ENGINE=${forced}，但对应的引擎或 compose 前端不可用"
  else
    PROBE_ERROR="未检测到可用的容器工具链"
  fi
  return 1
}

# 强制探测：失败即退出（需要容器引擎的子命令用这个）
detect_engine() {
  probe_engine && return 0
  if [ -n "${BLOG_ENGINE:-}" ]; then
    die "$PROBE_ERROR" "docker 需要 daemon 在运行；podman 需要 podman-compose 或 podman compose"
  fi
  die "$PROBE_ERROR" "支持：docker compose(v2) / docker-compose(v1) / podman-compose / podman compose"
}

compose() { "${COMPOSE_CMD[@]}" "$@"; }

# 镜像名：podman 把本地构建的镜像规范化为 localhost/<name>，docker 直接用 <name>
# （compose 里已显式声明 image:，因此两引擎的镜像名可预期）
# 但若实际存在的恰是“另一种命名”（例如把 podman 导出的离线包 load 进了 docker），
# 则以实际存在的为准，避免误报“镜像缺失”。
resolve_image_names() {
  local app_pref front_pref app_alt front_alt
  if [ "$ENGINE" = "docker" ]; then
    app_pref="my_blog_app:latest";          front_pref="my_blog_front:latest"
    app_alt="localhost/my_blog_app:latest"; front_alt="localhost/my_blog_front:latest"
  else
    app_pref="localhost/my_blog_app:latest"; front_pref="localhost/my_blog_front:latest"
    app_alt="my_blog_app:latest";            front_alt="my_blog_front:latest"
  fi
  APP_IMAGE="$app_pref";   FRONT_IMAGE="$front_pref"
  APP_ALT="$app_alt";      FRONT_ALT="$front_alt"
  if ! image_exists "$app_pref" && image_exists "$app_alt"; then APP_IMAGE="$app_alt"; fi
  if ! image_exists "$front_pref" && image_exists "$front_alt"; then FRONT_IMAGE="$front_alt"; fi
  IMAGES=("$APP_IMAGE" "$FRONT_IMAGE" "$NGINX_IMAGE" "docker.io/library/redis:7-alpine")
}

# 某个 compose 服务对应的容器名（podman-compose: <proj>_<svc>_1；docker compose: <proj>-<svc>-1）
container_of() {
  local svc="$1" name=""
  name="$("$ENGINE" ps -a --filter "label=com.docker.compose.service=${svc}" \
    --format '{{.Names}}' 2>/dev/null | head -1)"
  if [ -z "$name" ]; then
    name="$("$ENGINE" ps -a --format '{{.Names}}' 2>/dev/null \
      | grep -E "^${PROJECT}[-_]${svc}[-_][0-9]+$" | head -1)"
  fi
  printf '%s' "$name"
}
app_container() { container_of app; }

# 需要一个正在运行的 app 容器：返回容器名，否则退出
require_app_running() {
  local c
  c="$(app_container)"
  [ -n "$c" ] || die "app 容器未运行" "先执行 scripts/blog.sh up"
  printf '%s' "$c"
}

# docker 没有 `image exists` 子命令，统一用 inspect 判断
image_exists() { "$ENGINE" image inspect "$1" >/dev/null 2>&1; }
image_size()   { "$ENGINE" image inspect "$1" --format '{{.Size}}' 2>/dev/null || echo 0; }
image_mb()     { awk -v s="$(image_size "$1")" 'BEGIN{printf "%.0fMB", s/1024/1024}'; }

# 跨引擎导入：podman 导出的是 localhost/<name>，docker 期望 <name>（反之同理）→ 自动补标签
ensure_image_alias() {
  local want="$1" alt="$2"
  if ! image_exists "$want" && image_exists "$alt"; then
    "$ENGINE" tag "$alt" "$want" >/dev/null 2>&1 || die "无法把 $alt 追加标签为 $want"
    warn "跨引擎导入：已把 $alt 追加标签 $want"
  fi
}

require_tools() {
  command -v curl >/dev/null 2>&1 || die "未找到 curl" "Fedora: sudo dnf install -y curl"
  [ -n "$ENGINE" ] || detect_engine
  resolve_image_names
}

# 从 .env 读取某个键（不 source，避免执行任意代码）
env_value() {
  [ -f .env ] || return 1
  local value
  # 必须一并去掉 CR：.env 可能是在 Windows 上编辑的（CRLF），残留的 \r 会让
  # `[ "$mode" = prod ]` 之类比较静默失败（TEST-10 实测踩到），也会让下面的
  # 引号剥离失效（" 不在行尾）。
  value="$(sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" .env | tail -1 | tr -d '\r')"
  value="${value#\"}"; value="${value%\"}"    # 去双引号
  value="${value#\'}"; value="${value%\'}"    # 去单引号
  printf '%s' "$value"
}

check_env_file() {
  # 新克隆的仓库没有 .env（它被 gitignore，且含机器本地密钥，不应入库）：
  # 这里自动从 .env.example 生成一份，让「拉下来就能 up」，而不是直接报错退出。
  if [ ! -f .env ]; then
    if [ -f .env.example ]; then
      cp .env.example .env
      warn "未找到 .env，已从 .env.example 自动生成一份"
      hint "请按需修改 .env：DJANGO_ENV / DJANGO_SECRET_KEY / DJANGO_ALLOWED_HOSTS"
      hint "容器化部署建议 DJANGO_ENV=prod 且换成随机密钥：openssl rand -base64 48"
    else
      die "缺少 .env，且没有 .env.example 可参考" "请手动创建 .env（compose 的 env_file 必需）"
    fi
  fi
  local mode secret
  mode="$(env_value DJANGO_ENV || true)"
  secret="$(env_value DJANGO_SECRET_KEY || true)"
  if [ "${mode:-dev}" = "prod" ]; then
    [ -n "$secret" ] || die ".env 里 DJANGO_ENV=prod 但 DJANGO_SECRET_KEY 为空" "prod 下缺密钥会在容器内直接 RuntimeError"
  fi
  mkdir -p db_data
}

# http 状态码（--noproxy 保证本地探测不被宿主代理劫持）
http_code() {
  curl --noproxy '*' -s -o /dev/null -w '%{http_code}' --max-time 10 "$1" 2>/dev/null || echo "000"
}

health_check() {
  local failed=0 path code
  for path in "${HEALTH_PATHS[@]}"; do
    code="$(http_code "${BASE_URL}${path}")"
    if [ "$code" = "200" ]; then
      printf '  %s  %s → %s\n' "$C_OK✔$C_END" "$path" "$code"
    else
      printf '  %s  %s → %s\n' "$C_ERR✘$C_END" "$path" "$code"
      failed=1
    fi
  done
  return "$failed"
}

wait_ready() {
  local waited=0
  while [ "$waited" -lt "$WAIT_READY_TIMEOUT" ]; do
    if health_check >/dev/null 2>&1; then
      ok "${waited}s"
      return 0
    fi
    sleep 3
    waited=$((waited + 3))
    printf '.'
  done
  printf '\n'
  fail "等待 ${WAIT_READY_TIMEOUT}s 仍不就绪"
  hint "诊断：$ENGINE logs $(app_container) | tail -30"
  hint "      $ENGINE logs $(container_of nginx) | tail -20"
  return 1
}

containers_running() {
  [ -n "$("$ENGINE" ps --filter "label=com.docker.compose.project=${PROJECT}" --format '{{.Names}}' 2>/dev/null)" ] \
    || [ -n "$("$ENGINE" ps --format '{{.Names}}' 2>/dev/null | grep -E "^${PROJECT}[-_]" | head -1)" ]
}
containers_exist() {
  [ -n "$("$ENGINE" ps -a --filter "label=com.docker.compose.project=${PROJECT}" --format '{{.Names}}' 2>/dev/null)" ] \
    || [ -n "$("$ENGINE" ps -a --format '{{.Names}}' 2>/dev/null | grep -E "^${PROJECT}[-_]" | head -1)" ]
}

# 校验容器实际使用的镜像 == latest（防止 podman-compose 复用旧镜像）
verify_container_image() {
  local container="$1" image="$2" cid iid
  cid="$("$ENGINE" inspect "$container" --format '{{.Image}}' 2>/dev/null || true)"
  iid="$("$ENGINE" image inspect "$image" --format '{{.Id}}' 2>/dev/null || true)"
  if [ -n "$cid" ] && [ "$cid" != "$iid" ]; then
    die "容器 $container 仍在使用旧镜像" "执行 scripts/blog.sh down && scripts/blog.sh up"
  fi
}

human_size() { numfmt --to=iec --suffix=B "$1" 2>/dev/null || echo "$1 B"; }

norm_arch() {
  case "$(uname -m)" in
    x86_64|amd64) echo amd64 ;;
    aarch64|arm64) echo arm64 ;;
    *) uname -m ;;
  esac
}

# --------------------------------------------------------------------------- preflight
cmd_preflight() {
  title "环境体检"
  step "容器工具链"
  require_tools
  ok "$ENGINE $("$ENGINE" --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1) · ${COMPOSE_CMD[*]} · ${ENGINE_SOURCE}"
  if [ -n "${BLOG_ENGINE:-}" ]; then
    hint "（由 BLOG_ENGINE=${BLOG_ENGINE} 显式指定）"
  fi

  step "架构"
  ok "$(uname -m)（镜像标识 $(norm_arch)）"

  step "SELinux"
  local selinux="未启用"
  command -v getenforce >/dev/null 2>&1 && selinux="$(getenforce)"
  if [ "$selinux" = "Enforcing" ]; then
    ok "Enforcing（挂载已带 :z，脚本与 compose 已处理）"
  else
    ok "$selinux"
  fi

  step "端口 ${NGINX_PORT}"
  if ss -tln 2>/dev/null | grep -q ":${NGINX_PORT} "; then
    if containers_running; then ok "已被本项目的 nginx 占用（正常）"
    else die "端口 ${NGINX_PORT} 被其他进程占用" "lsof -i :${NGINX_PORT}  # 或改 docker-compose.yml 的 ports"; fi
  else
    ok "空闲"
  fi

  step "磁盘余量"
  local avail
  avail="$(df -Pk . | awk 'NR==2{print $4}')"
  if [ "$avail" -lt 3145728 ]; then
    warn "$(df -h . | awk 'NR==2{print $4}')（建议 ≥3GB：镜像 ~640MB + 导出包 ~610MB）"
  else
    ok "$(df -h . | awk 'NR==2{print $4}') 可用"
  fi

  step "配置语法"
  python3 -c "import yaml,sys; yaml.safe_load(open('docker-compose.yml'))" \
    || die "docker-compose.yml 语法错误" "python3 -c \"import yaml;yaml.safe_load(open('docker-compose.yml'))\""
  sh -n docker/entrypoint.sh || die "docker/entrypoint.sh 语法错误"
  ok "compose YAML + entrypoint.sh"

  step ".env"
  if [ -f .env ]; then
    check_env_file
    ok "DJANGO_ENV=$(env_value DJANGO_ENV || echo dev)，必需项已满足"
  else
    warn "缺少 .env（up 时会自动从 .env.example 生成，之后再按需修改）"
  fi
}

# --------------------------------------------------------------------------- up / down
cmd_up() {
  local do_build=0
  for arg in "$@"; do [ "$arg" = "--build" ] && do_build=1; done

  title "启动（构建 → 重建 → 等待就绪 → 健康检查）"
  step "检查工具与环境变量"
  require_tools
  check_env_file
  ok ".env 就绪，db_data/ 就绪"

  if [ "$do_build" = "1" ]; then
    block_step "构建镜像"
    if ! compose build 2>&1 | sed 's/^/    /'; then
      die "镜像构建失败" "查看上面的构建输出"
    fi
    ok "app $(image_mb "$APP_IMAGE") · front $(image_mb "$FRONT_IMAGE")"
  fi

  step "重建容器"
  # 必须先 down：podman-compose 不会因镜像变更重建容器（docker compose 会，但统一处理更省心）
  if containers_exist; then
    compose down >/dev/null 2>&1 || true
  fi
  compose up -d >/dev/null 2>&1 || die "容器启动失败" "${COMPOSE_CMD[*]} up -d  # 看完整输出"
  verify_container_image "$(app_container)" "$APP_IMAGE"
  ok "已按最新镜像重建"

  step "等待就绪"
  wait_ready

  step "重载 nginx 配置"
  # nginx.conf 是 bind mount：若有人绕开本脚本用 `up -d`（不 down）改配置，容器不会重建，
  # 这里显式 reload 一次兜底（down+up 已经重建过，reload 属幂等）。
  local ngx
  ngx="$(container_of nginx)"
  if [ -n "$ngx" ] && "$ENGINE" exec "$ngx" nginx -s reload >/dev/null 2>&1; then
    ok "nginx 配置已重载"
  else
    warn "nginx 未运行或重载失败（若刚重建过容器，配置其实已生效）"
  fi

  step "健康检查"
  health_check || die "健康检查未全部通过" "$ENGINE logs $(app_container) | tail -30"
  printf '\n%s服务已就绪%s → %s%s/%s\n' "$C_OK" "$C_END" "$C_BOLD" "$BASE_URL" "$C_END"
}

cmd_down() {
  local purge=0 yes=0
  for arg in "$@"; do
    [ "$arg" = "--purge" ] && purge=1
    [ "$arg" = "--yes" ] && yes=1
  done
  require_tools
  if ! containers_exist; then
    printf '没有正在运行的容器\n'; return 0
  fi
  if [ "$purge" = "1" ]; then
    printf '%s将删除以下数据卷（文章图片/附件、归档产物、静态文件）:%s\n' "$C_WARN" "$C_END"
    local vols
    vols="$("$ENGINE" volume ls --filter "label=com.docker.compose.project=${PROJECT}" --format '{{.Name}}' 2>/dev/null)"
    [ -n "$vols" ] || vols="$("$ENGINE" volume ls --format '{{.Name}}' | grep "^${PROJECT}_")"
    printf '%s\n' "$vols" | grep -v '^$' | sed 's/^/  - /'
    printf '%s注意：SQLite 数据库在 bind mount 的 db_data/ 里，不会被删除；确需清空请自行 rm -rf db_data%s\n' "$C_DIM" "$C_END"
    if [ "$yes" != "1" ]; then
      read -r -p "确认删除？输入 yes 继续: " ans
      [ "$ans" = "yes" ] || { printf '已取消\n'; return 1; }
    fi
    compose down -v >/dev/null 2>&1 || true
    printf '容器与数据卷已删除\n'
  else
    compose down >/dev/null 2>&1 || true
    printf '容器已停止（数据卷与 db_data/ 保留）\n'
  fi
}

cmd_restart() { cmd_down; cmd_up "$@"; }

# --------------------------------------------------------------------------- status / logs
cmd_status() {
  require_tools
  title "容器"
  "$ENGINE" ps -a --filter "label=com.docker.compose.project=${PROJECT}" \
    --format '  {{.Names}}\t{{.Status}}\t{{.Image}}' || true

  title "镜像"
  local total=0 size
  for img in "${IMAGES[@]}"; do
    if image_exists "$img"; then
      size="$(image_size "$img")"
      total=$((total + size / 1024 / 1024))
      printf '  %-44s %s\n' "$img" "$(awk -v s="$size" 'BEGIN{printf "%.0f MB", s/1024/1024}')"
    else
      printf '  %-44s %s缺失%s\n' "$img" "$C_ERR" "$C_END"
    fi
  done
  printf '  合计约 %s MB\n' "$total"

  title "健康检查"
  if containers_running; then health_check || warn "存在未通过的路径"; else warn "容器未运行"; fi

  title "归档产物"
  local app
  app="$(app_container)"
  if [ -n "$app" ]; then
    "$ENGINE" exec "$app" sh -c '
      for d in staging exports rollbacks; do
        printf "  %-10s %s 项\n" "$d" "$(ls -A /app/private_archives/$d 2>/dev/null | wc -l)"
      done' 2>/dev/null || warn "无法读取"
  else
    warn "app 容器未运行"
  fi

  title "磁盘"
  printf '  项目目录: %s\n' "$(df -h . | awk 'NR==2{print $4" 可用"}')"
  printf '  容器存储: %s\n' "$(du -sh "${HOME}/.local/share/containers/storage" 2>/dev/null | awk '{print $1}')"
}

cmd_logs() {
  require_tools
  local svc="app" follow=""
  for arg in "$@"; do
    case "$arg" in
      -f|--follow) follow="-f" ;;
      app|nginx|front|redis) svc="$arg" ;;
      *) die "未知服务：$arg" "可选：app | nginx | front | redis" ;;
    esac
  done
  local container
  container="$(container_of "$svc")"
  [ -n "$container" ] || die "服务 $svc 的容器不存在" "先执行 scripts/blog.sh up"
  # shellcheck disable=SC2086
  "$ENGINE" logs $follow "$container"
}

# --------------------------------------------------------------------------- check
cmd_check() {
  # 前端类型检查默认纳入门禁（FE-13）；无前端依赖时降级为 warn。用 --no-front 显式跳过。
  # --e2e 额外在**正在运行的容器**上打真实链路冒烟（TEST-09），需先 up。
  local with_front=1 with_e2e=0
  for arg in "$@"; do
    [ "$arg" = "--no-front" ] && with_front=0
    [ "$arg" = "--e2e" ] && with_e2e=1
  done
  command -v uv >/dev/null 2>&1 || die "未找到 uv" "https://docs.astral.sh/uv/"
  mkdir -p db_data
  title "质量门禁"
  run_show "ruff" uv run --frozen ruff check .
  run_show "mypy" uv run --frozen mypy config articles common users
  run_show_tail "pytest" 3 uv run --frozen pytest -q

  # DOC-07：文档漂移自查 —— ① AGENTS.md 声明的用例数必须等于实际 collection（迭代新增
  # 用例后文档会静默过期）；② AGENTS.md 引用的 docs/*.md 必须存在（文件改名后易漏改）。
  # 用 --collect-only（不执行用例，秒级），失败即阻断。
  # 注意管道写法：脚本开了 pipefail，`grep | head -1` 这类**下游提前退出**的命令会因
  # SIGPIPE 让管道非零、被 set -e 直接中断（实测）。这里改为「先整体取回再处理」。
  step "文档漂移自查"
  local declared actual missing docs_ref collect_out
  declared="$(sed -nE '/当前 [0-9]+ 个/{s/.*当前 ([0-9]+) 个.*/\1/p; q;}' AGENTS.md)"
  collect_out="$(uv run --frozen pytest --collect-only -q 2>/dev/null || true)"
  actual="$(printf '%s\n' "$collect_out" | grep -oE '[0-9]+ tests? collected' | tr -dc '0-9')"
  if [ -z "$declared" ] || [ -z "$actual" ]; then
    warn "无法提取用例数（声明=${declared:-无}，实际=${actual:-无}），跳过该项"
  elif [ "$declared" != "$actual" ]; then
    die "AGENTS.md 声明 ${declared} 个用例，实际 ${actual} 个" "把 AGENTS.md 的「当前 N 个」同步为 ${actual}"
  fi
  missing=""
  while IFS= read -r docs_ref; do
    [ -f "$docs_ref" ] || missing="$missing $docs_ref"
  done < <(grep -oE 'docs/[A-Za-z0-9_]+\.md' AGENTS.md | sort -u)
  [ -z "$missing" ] || die "AGENTS.md 引用了不存在的文档：$missing"
  ok "${actual:-?} 个用例 · docs 引用齐全"
  step "迁移一致性"; uv run --frozen python manage.py makemigrations --check --dry-run >/dev/null 2>&1 \
                       || die "存在未生成的迁移" "uv run python manage.py makemigrations"; ok
  block_step "配置语法"
  python3 -c "import yaml;yaml.safe_load(open('docker-compose.yml'))" || die "compose YAML 错误"
  sh -n docker/entrypoint.sh || die "docker/entrypoint.sh 语法错误"
  bash -n scripts/blog.sh || die "scripts/blog.sh 语法错误"
  # nginx -t 是必检项，但依赖「容器工具链 + nginx 镜像」。区分两种情况：
  #  - 有工具链但缺镜像 → 先尝试拉取一次（离线环境拉不到再降级 warn，不阻断 lint）；
  #  - 完全没有工具链 → 属环境限制，降级 warn（可选增强）。
  # 能跑起来时，nginx.conf 语法错误一律阻断。
  if ! probe_engine; then
    warn "未检测到容器工具链，跳过 nginx -t（可选增强）"
  elif image_exists "$NGINX_IMAGE" || "$ENGINE" pull "$NGINX_IMAGE" >/dev/null 2>&1; then
    "$ENGINE" run --rm --add-host app:127.0.0.1 --add-host front:127.0.0.1 \
      -v "$ROOT_DIR/docker/nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro,z" \
      "$NGINX_IMAGE" nginx -t >/dev/null 2>&1 || die "nginx.conf 语法错误"
  else
    warn "无法获取 nginx 镜像（$NGINX_IMAGE），跳过 nginx -t（可选增强）"
  fi
  ok

  # ShellCheck：装了就跑（必检），未装降级 warn（可选增强）。规则见仓库根 .shellcheckrc。
  step "shellcheck"
  if command -v shellcheck >/dev/null 2>&1; then
    shellcheck scripts/blog.sh 2>&1 | sed 's/^/    /' || { fail "shellcheck 未通过"; exit 1; }
    ok
  else
    warn "未安装 shellcheck，跳过（可选增强；Fedora: sudo dnf install -y ShellCheck）"
  fi

  if [ "$with_front" = "1" ]; then
    if [ ! -f front/node_modules/vue-tsc/bin/vue-tsc.js ]; then
      warn "front 依赖未安装，跳过 ESLint / vue-tsc / vitest（先 cd front && npm ci）"
    else
      # FE-14：ESLint 纳入默认门禁（配置见 front/eslint.config.mjs，复用 vue-tsc 的依赖探测）
      step "前端 lint（ESLint）"
      (cd front && node node_modules/eslint/bin/eslint.js .) || die "ESLint 未通过" "cd front && npm run lint"
      ok
      step "前端类型检查（vue-tsc）"
      if containers_running; then
        warn "检测到本项目容器在运行；vue-tsc 会重写 front/.nuxt，与 nuxt dev 冲突"
      fi
      (cd front && node node_modules/vue-tsc/bin/vue-tsc.js --noEmit) || die "vue-tsc 未通过"
      (cd front && node node_modules/vitest/vitest.mjs run) || die "前端单元测试未通过"
      ok
    fi
  else
    hint "（已用 --no-front 跳过前端类型检查）"
  fi

  if [ "$with_e2e" = "1" ]; then
    cmd_e2e
  fi
}

# --------------------------------------------------------------------------- e2e 冒烟
# TEST-09：在**已运行的容器**上打真实链路（nginx → gunicorn → SQLite），
# 覆盖 issue 建议的三步：登录 → 建文章 → 导出。仅部署机（有容器引擎）可跑。
# 用随机用户名 + 随机密码建临时管理员，全程走公开 HTTP 接口，结束时清理临时数据。
E2E_USER=""
E2E_ARTICLE_ID=""
E2E_TOKEN=""
E2E_TMPDIR=""

e2e_cleanup() {
  # 清理是尽力而为：即使某步失败也不应改变脚本退出码（它常作为 EXIT trap 运行）
  set +e
  local app
  app="$(app_container)"
  if [ -n "$app" ]; then
    if [ -n "$E2E_ARTICLE_ID" ] && [ -n "$E2E_TOKEN" ]; then
      # 删除文章会经 post_delete 信号同步清理封面文件
      curl --noproxy '*' -s -o /dev/null -X DELETE \
        -H "Authorization: Bearer $E2E_TOKEN" \
        "${BASE_URL}/api/v1/admin/articles/${E2E_ARTICLE_ID}/"
    fi
    if [ -n "$E2E_USER" ]; then
      "$ENGINE" exec "$app" python -c "
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from django.contrib.auth import get_user_model
get_user_model().objects.filter(username='$E2E_USER').delete()
" >/dev/null 2>&1
    fi
  fi
  [ -n "$E2E_TMPDIR" ] && rm -rf "$E2E_TMPDIR"
  E2E_USER=""; E2E_ARTICLE_ID=""; E2E_TOKEN=""; E2E_TMPDIR=""
  set -e
}

cmd_e2e() {
  require_tools
  if ! containers_running; then
    die "端到端冒烟需要容器在运行" "先执行 scripts/blog.sh up；本机无容器工具链时请在部署机执行"
  fi
  local app
  app="$(app_container)"
  E2E_TMPDIR="$(mktemp -d)"
  trap e2e_cleanup EXIT

  title "端到端冒烟（nginx → gunicorn → SQLite）"
  step "健康探活"
  health_check || die "健康检查未通过" "$ENGINE logs $app | tail -30"
  ok

  # 1) 登录：容器内惰性建一个随机密码的临时管理员，走真实 POST /login/
  #    （随机用户名可避开登录失败限流的按 IP+用户名 计数）
  step "登录（POST /api/v1/login/）"
  E2E_USER="e2e_smoke_$(date +%s)_$$"
  local pass resp
  pass="$("$ENGINE" exec "$app" python -c 'import secrets;print(secrets.token_urlsafe(12))' | tail -1)"
  "$ENGINE" exec "$app" python -c "
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from django.contrib.auth import get_user_model
U = get_user_model()
u, _ = U.objects.get_or_create(username='$E2E_USER', defaults={'is_staff': True, 'is_superuser': True})
u.is_staff = True; u.is_superuser = True
u.set_password('$pass'); u.save()
" || die "创建临时管理员失败"
  resp="$(curl --noproxy '*' -s --max-time 30 -H 'Content-Type: application/json' \
        -d "{\"username\":\"$E2E_USER\",\"password\":\"$pass\"}" \
        "${BASE_URL}/api/v1/login/")"
  E2E_TOKEN="$(printf '%s' "$resp" | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["access"])' 2>/dev/null || true)"
  [ -n "$E2E_TOKEN" ] || die "登录失败：$(printf '%s' "$resp" | head -c 200)"
  ok "已签发 access"

  # 2) 建文章：multipart（临时封面 + 正文），封面由容器内 Pillow 生成
  step "创建文章（POST /api/v1/admin/articles/）"
  local cover="$E2E_TMPDIR/cover.png"
  "$ENGINE" exec "$app" python -c "
from PIL import Image
Image.new('RGB', (64, 48), (60, 120, 200)).save('/tmp/e2e_cover.png')
" || die "生成测试封面失败"
  "$ENGINE" cp "$app:/tmp/e2e_cover.png" "$cover" >/dev/null
  resp="$(curl --noproxy '*' -s --max-time 60 -H "Authorization: Bearer $E2E_TOKEN" \
        -F "title=E2E 冒烟 $(date +%s)" \
        -F "publish_time=$(date -Iseconds)" \
        -F "content=E2E smoke test，由 scripts/blog.sh check --e2e 创建，随后删除。" \
        -F "is_published=false" \
        -F "cover=@$cover;type=image/png" \
        "${BASE_URL}/api/v1/admin/articles/")"
  E2E_ARTICLE_ID="$(printf '%s' "$resp" | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["id"])' 2>/dev/null || true)"
  [ -n "$E2E_ARTICLE_ID" ] || die "创建文章失败：$(printf '%s' "$resp" | head -c 200)"
  ok "id=${E2E_ARTICLE_ID}"

  # 3) 导出 + 下载：导出返回一次性能力 URL，下载走 nginx 直链，校验 zip 头
  step "导出文章（GET /api/v1/admin/articles/export/）"
  resp="$(curl --noproxy '*' -s --max-time 120 -H "Authorization: Bearer $E2E_TOKEN" \
        "${BASE_URL}/api/v1/admin/articles/export/?ids=${E2E_ARTICLE_ID}")"
  local dl
  dl="$(printf '%s' "$resp" | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["download_url"])' 2>/dev/null || true)"
  [ -n "$dl" ] || die "导出失败：$(printf '%s' "$resp" | head -c 200)"
  step "下载导出包"
  curl --noproxy '*' -s --max-time 120 -o "$E2E_TMPDIR/export.zip" "${BASE_URL}${dl}"
  local magic
  magic="$(head -c 2 "$E2E_TMPDIR/export.zip" 2>/dev/null || true)"
  [ "$magic" = "PK" ] || die "导出包不是合法 zip（magic=${magic}）"
  ok "$(human_size "$(stat -c%s "$E2E_TMPDIR/export.zip")")"

  printf '\n%s端到端冒烟通过%s（临时文章/管理员已清理）\n' "$C_OK" "$C_END"
  e2e_cleanup
  trap - EXIT
}

# --------------------------------------------------------------------------- export / import
cmd_export() {
  local out=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --out)
        # 值可选：只有「后面确实跟着一个不以 - 开头的值」才取用，否则回落到默认文件名。
        # 旧写法 `shift 2` 在只剩 `--out` 一个参数时会失败，被 set -e 直接终止脚本（静默退出码 1）。
        if [ $# -ge 2 ] && [ "${2#-}" = "${2:-}" ]; then
          out="$2"; shift 2
        else
          shift
        fi
        ;;
      *) die "未知参数：$1" ;;
    esac
  done
  require_tools
  # 默认文件名带架构与时间戳：不写 --out 也能直接用，且同一天多次导出不会互相覆盖
  if [ -z "$out" ]; then
    out="${EXPORT_DIR_DEFAULT}/my_blog_images_$(norm_arch)_$(date +%Y%m%d-%H%M%S).tar"
    hint "未指定 --out，导出为默认名：$(basename "$out")"
  fi

  title "导出离线镜像包"
  step "校验镜像"
  local img
  for img in "${IMAGES[@]}"; do
    image_exists "$img" || die "镜像缺失：$img" "先执行 scripts/blog.sh up --build"
  done
  ok "${#IMAGES[@]} 个镜像齐备"

  mkdir -p "$(dirname "$out")"
  block_step "打包"
  # docker save 默认即 docker-archive 多镜像格式；podman 需显式 --format 与 -m
  local save_args=()
  if [ "$ENGINE" = "podman" ]; then
    save_args=(--format docker-archive -m)
  fi
  if ! "$ENGINE" save ${save_args[@]+"${save_args[@]}"} -o "$out" "${IMAGES[@]}" 2>&1 | sed 's/^/    /'; then
    die "$ENGINE save 失败"
  fi
  # GNU 标准格式 "<hash>  <文件名>"：这样目标机上 sha256sum -c xxx.tar.sha256 可直接校验
  ( cd "$(dirname "$out")" && sha256sum "$(basename "$out")" ) > "${out}.sha256"
  ok "$(human_size "$(stat -c%s "$out")")"

  step "校验和"
  ok "$(awk '{print $1}' "${out}.sha256")"
  printf '\n产物：%s%s%s\n' "$C_BOLD" "$out" "$C_END"
  printf '  目标机：%s load -i %s\n' "$ENGINE" "$(basename "$out")"
  printf '  或直接：scripts/blog.sh import --in %s\n' "$out"
}

cmd_import() {
  local in="" yes=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --in)
        # 同 --out：值可选（不以 - 开头才当作值），省略时自动选用导出目录下最新的包
        if [ $# -ge 2 ] && [ "${2#-}" = "${2:-}" ]; then
          in="$2"; shift 2
        else
          shift
        fi
        ;;
      --yes) yes=1; shift ;;
      *) die "未知参数：$1" ;;
    esac
  done
  require_tools

  if [ -z "$in" ]; then
    in="$(ls -t "${EXPORT_DIR_DEFAULT}"/my_blog_images_*.tar 2>/dev/null | head -1 || true)"
    [ -n "$in" ] || die "未指定 --in，且 ${EXPORT_DIR_DEFAULT} 下没有镜像包"
    hint "自动选用最新包：$in"
  fi
  [ -f "$in" ] || die "文件不存在：$in"

  title "导入离线镜像包并部署"
  step "校验校验和"
  if [ -f "${in}.sha256" ]; then
    local expect actual
    expect="$(awk '{print $1}' "${in}.sha256")"   # 兼容裸哈希与 "<hash>  <file>" 两种格式
    actual="$(sha256sum "$in" | awk '{print $1}')"
    [ "$expect" = "$actual" ] || die "sha256 不匹配（文件可能损坏或传输不完整）" "期望 ${expect:0:16}… 实际 ${actual:0:16}…"
    ok "${actual:0:16}…"
  else
    warn "缺少 ${in}.sha256，跳过校验"
  fi

  step "架构"
  local tar_arch host_arch
  tar_arch="$(basename "$in" | grep -oE '_(amd64|arm64)_' | tr -d '_' || true)"
  host_arch="$(norm_arch)"
  if [ -n "$tar_arch" ] && [ "$tar_arch" != "$host_arch" ]; then
    die "镜像包架构（${tar_arch}）与本机（${host_arch}）不一致" "需在对应架构的机器上重新 export"
  fi
  ok "${tar_arch:-未标注} / 本机 ${host_arch}"

  step "磁盘余量"
  local need avail
  need="$(stat -c%s "$in")"
  avail="$(df -Pk "$(dirname "$in")" | awk 'NR==2{print $4*1024}')"
  if [ "$avail" -lt $((need * 3 / 2)) ]; then
    die "磁盘不足（镜像解包后约需 $(human_size "$((need * 3 / 2))")）" "清理后重试"
  fi
  ok "$(human_size "$avail") 可用"

  step "加载镜像"
  "$ENGINE" load -i "$in" >/dev/null 2>&1 || die "$ENGINE load 失败"
  local img alt
  for img in "${IMAGES[@]}"; do
    # 跨引擎导入时按镜像各自的目标名补标签（前端不能借用 app 的别名，否则会给
    # nginx/redis 也乱打 app 标签）
    case "$img" in
      "$APP_IMAGE"|"$APP_ALT")     alt="$APP_ALT" ;;
      "$FRONT_IMAGE"|"$FRONT_ALT") alt="$FRONT_ALT" ;;
      *)                           alt="" ;;
    esac
    if ! image_exists "$img" && [ -n "$alt" ]; then
      ensure_image_alias "$img" "$alt"
    fi
    image_exists "$img" || die "加载后仍缺镜像：$img"
  done
  ok "${#IMAGES[@]} 个镜像已就绪"

  step "环境变量"
  check_env_file
  ok ".env 就绪"

  step "重建容器（不使用 --build，直接用已加载镜像）"
  # 这里**绝不能** build：podman-compose build 不看镜像是否已存在，一律把构建重跑一遍，
  # 于是会用**目标机本地源码**覆盖刚 load 进来的镜像；若目标机源码没同步到最新，就悄悄
  # 退回旧代码，而且容器与 latest 都是那个旧镜像，verify_container_image 也发现不了。
  # 上面已逐个确认四个镜像就绪，这里只做 down + up。
  if containers_exist; then compose down >/dev/null 2>&1 || true; fi
  compose up -d >/dev/null 2>&1 || die "容器启动失败" "${COMPOSE_CMD[*]} up -d"
  verify_container_image "$(app_container)" "$APP_IMAGE"
  ok

  step "等待就绪"; wait_ready
  step "健康检查"; health_check || die "健康检查未通过" "$ENGINE logs $(app_container) | tail -30"
  printf '\n%s部署完成%s → %s%s/%s\n' "$C_OK" "$C_END" "$C_BOLD" "$BASE_URL" "$C_END"

  # OPS-06：媒体卷是命名卷，不随镜像带入。若本机有 media 数据而容器内为空，
  # 文章封面/附件会 404 —— 这里显式自检（此前只有一行易被忽略的 hint）。
  # 容器不可达时 exec 失败 → 拿到空串 → 两个分支都不进，不会误告警。
  if [ -d media ] && [ "$(ls -A media/covers 2>/dev/null | wc -l)" -gt 0 ]; then
    local c_app c_counts c_covers c_files
    c_app="$(app_container)"
    c_counts="$("$ENGINE" exec "$c_app" sh -c \
      'printf "%s %s" "$(ls -A /app/media/covers 2>/dev/null | wc -l)" "$(ls -A /app/media/files 2>/dev/null | wc -l)"' \
      2>/dev/null || true)"
    c_covers="${c_counts%% *}"; c_files="${c_counts##* }"
    if [ "$c_covers" = "0" ] && [ "$c_files" = "0" ]; then
      if [ "$yes" = "1" ]; then
        warn "媒体卷为空，自动执行 seed-media（本机 media/ → 容器）"
        cmd_seed_media
      else
        warn "媒体卷为空：文章封面/附件会 404"
        hint "请执行 scripts/blog.sh seed-media（或 import 加 --yes 自动同步）"
      fi
    else
      ok "媒体卷：covers ${c_covers} / files ${c_files}"
    fi
  fi
}

# --------------------------------------------------------------------------- seed-media / seed-demo / purge
cmd_seed_media() {
  require_tools
  local app
  app="$(require_app_running)"
  [ -d media ] || die "本机没有 media/ 目录"
  title "把宿主机 media/ 同步进媒体卷"
  local n_covers n_files
  n_covers="$(ls -A media/covers 2>/dev/null | wc -l)"
  n_files="$(ls -A media/files 2>/dev/null | wc -l)"
  printf '  本机：covers %s 个 / files %s 个\n' "$n_covers" "$n_files"
  [ "$n_covers" -gt 0 ] || warn "media/covers 为空，跳过"
  "$ENGINE" cp media/. "$app:/app/media/" || die "$ENGINE cp 失败"
  printf '  容器内：covers %s 个 / files %s 个\n' \
    "$("$ENGINE" exec "$app" sh -c 'ls -A /app/media/covers | wc -l')" \
    "$("$ENGINE" exec "$app" sh -c 'ls -A /app/media/files | wc -l')"
  ok
}

cmd_seed_demo() {
  local count=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --count) count="${2:-}"; shift 2 ;;
      *) die "未知参数：$1" ;;
    esac
  done
  require_tools
  local app
  app="$(require_app_running)"

  title "生成并导入演示游记"
  step "生成归档包（容器内）"
  local gen_args="--out /tmp/seed_demo.zip"
  [ -n "$count" ] && gen_args="$gen_args --count $count"
  # shellcheck disable=SC2086
  "$ENGINE" exec "$app" python /app/scripts/seed_demo.py $gen_args | sed 's/^/  /'
  "$ENGINE" cp "$app:/tmp/seed_demo.zip" /tmp/seed_demo.zip >/dev/null
  ok "$(human_size "$(stat -c%s /tmp/seed_demo.zip)")"

  step "取管理员令牌"
  local token
  token="$("$ENGINE" exec "$app" python -c "
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from django.contrib.auth import get_user_model
from ninja_jwt.tokens import RefreshToken
user = get_user_model().objects.filter(is_superuser=True).order_by('id').first()
print(str(RefreshToken.for_user(user).access_token) if user else '')
" 2>/dev/null | tail -1)"
  [ -n "$token" ] || die "无法获取管理员令牌（是否已创建超级用户？）" "uv run python manage.py createsuperuser"
  ok "已获取"

  step "预检（上传）"
  local resp staged
  resp="$(curl --noproxy '*' -s --max-time 300 -H "Authorization: Bearer $token" \
        -F "file=@/tmp/seed_demo.zip;type=application/zip" -F "strategy=skip" \
        "${BASE_URL}/api/v1/admin/articles/import/stage/")"
  staged="$(printf '%s' "$resp" | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["staged_id"])' 2>/dev/null || true)"
  [ -n "$staged" ] || die "预检失败：$(printf '%s' "$resp" | head -c 200)"
  printf '%s' "$resp" | python3 -c 'import sys,json;print("  ",json.load(sys.stdin)["data"]["totals"])'

  step "提交导入"
  curl --noproxy '*' -s --max-time 300 -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
    -d "{\"staged_id\":\"$staged\",\"strategy\":\"skip\"}" \
    "${BASE_URL}/api/v1/admin/articles/import/commit/" \
    | python3 -c 'import sys,json;d=json.load(sys.stdin)["data"];print("  ",d["totals"])' \
    || die "提交失败"
  rm -f /tmp/seed_demo.zip
  ok
  printf '\n%s演示数据就绪%s → %s%s/%s\n' "$C_OK" "$C_END" "$C_BOLD" "$BASE_URL" "$C_END"
}

cmd_purge() {
  require_tools
  title "清理"
  step "归档过期产物"
  local app
  app="$(app_container)"
  if [ -n "$app" ]; then
    "$ENGINE" exec "$app" python manage.py purge_archives 2>/dev/null | tail -1 | sed 's/^/  /'
    ok
  else
    warn "app 容器未运行，跳过"
  fi
  step "悬空镜像"
  "$ENGINE" image prune -f >/dev/null 2>&1 || true
  ok "当前悬空镜像 $("$ENGINE" images --filter dangling=true -q | wc -l) 个"
}

# --------------------------------------------------------------------------- backup
# 备份 SQLite（db_data/db.sqlite3，宿主机 bind mount）。恢复步骤见 docs/BACKUP_RESTORE.md。
cmd_backup() {
  local out=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --out)
        # 与 export/import 一致：值可选（不以 - 开头才当值），省略时用默认名
        if [ $# -ge 2 ] && [ "${2#-}" = "${2:-}" ]; then
          out="$2"; shift 2
        else
          shift
        fi
        ;;
      *) die "未知参数：$1" ;;
    esac
  done

  local db="db_data/db.sqlite3"
  [ -f "$db" ] || die "未找到 $db" "容器首次 migrate 前无此文件，先 scripts/blog.sh up"
  if [ -z "$out" ]; then
    mkdir -p "$BACKUP_DIR_DEFAULT"
    out="${BACKUP_DIR_DEFAULT}/my_blog_db_$(date +%Y%m%d-%H%M%S).sqlite3"
  fi
  mkdir -p "$(dirname "$out")"

  require_tools
  title "备份 SQLite 数据库"
  local app tmp
  app="$(app_container)"
  # 临时文件放 db_data/ 内（bind mount）：这样容器与宿主机都能访问同一份，便于用容器内
  # python 做一致性备份与校验；最后再 mv 到目标路径（可能在另一文件系统）。
  tmp="db_data/.backup.$$.sqlite3"
  trap 'rm -f "$tmp"' EXIT

  # 优先宿主 sqlite3（.backup 是热备，有并发写也一致）；否则借运行中容器的 python
  # sqlite3.backup()（同样安全）；两者都没有才退回 cp，并明确提示一致性风险。
  if command -v sqlite3 >/dev/null 2>&1; then
    step "sqlite3 .backup（热备）"; sqlite3 "$db" ".backup '$tmp'" || die "sqlite3 .backup 失败"; ok
  elif [ -n "$app" ]; then
    step "容器内 python sqlite3.backup（热备）"
    "$ENGINE" exec "$app" python -c \
      "import sqlite3;s=sqlite3.connect('/app/$db');d=sqlite3.connect('/app/$tmp');s.backup(d);d.close();s.close()" \
      || die "容器内备份失败"; ok
  else
    warn "宿主无 sqlite3 且 app 容器未运行，退回 cp —— 若有写入可能拿到不一致快照"
    step "cp（冷备，非事务安全）"; cp "$db" "$tmp" || die "cp 失败"; ok
  fi

  step "校验完整性"
  local integrity=""
  if command -v sqlite3 >/dev/null 2>&1; then
    integrity="$(sqlite3 "$tmp" 'PRAGMA integrity_check;' 2>/dev/null | head -1 || true)"
  elif [ -n "$app" ]; then
    integrity="$("$ENGINE" exec "$app" python -c \
      "import sqlite3;print(sqlite3.connect('/app/$tmp').execute('PRAGMA integrity_check').fetchone()[0])" \
      2>/dev/null || true)"
  fi
  if [ "$integrity" = "ok" ]; then
    ok "integrity_check = ok"
  elif [ -z "$integrity" ]; then
    warn "无法校验（缺 sqlite3 工具），已跳过 integrity_check"
  else
    die "备份校验失败：$integrity"
  fi

  mv "$tmp" "$out"
  if ( cd "$(dirname "$out")" && sha256sum "$(basename "$out")" ) > "${out}.sha256" 2>/dev/null; then
    ok "校验和 → ${out}.sha256"
  else
    warn "sha256sum 不可用，未生成校验和"
  fi
  printf '\n%s备份完成%s → %s%s%s（%s）\n' "$C_OK" "$C_END" "$C_BOLD" "$out" "$C_END" "$(human_size "$(stat -c%s "$out")")"
  hint "恢复步骤见 docs/BACKUP_RESTORE.md"
}

# --------------------------------------------------------------------------- 入口
cmd_install_hooks() {
  [ -d .git ] || die "当前目录不是 git 仓库" "在仓库根目录执行"
  # 钩子文件是需要可执行位的；Windows/NTFS 上 chmod 可能无效，失败不阻断（git 只看索引里的模式位）
  chmod +x scripts/hooks/* 2>/dev/null || true
  git config core.hooksPath scripts/hooks
  ok "已启用仓库钩子：core.hooksPath=scripts/hooks"
  hint "pre-push 会跑 scripts/blog.sh check；临时跳过用 git push --no-verify"
}

usage() {
  cat <<'EOF'
用法：scripts/blog.sh <子命令> [选项]

  preflight              环境体检（引擎探测/架构/SELinux/端口/磁盘/配置语法）
  up [--build]           构建（可选）→ 重建容器 → 等待就绪 → 健康检查
  down [--purge]         停止容器（--purge 连数据卷一起删，需确认）
  restart [--build]      等价于 down + up
  status                 容器/镜像/端口/健康/归档产物/磁盘 一览
  logs [服务] [-f]       查看日志（app|nginx|front|redis，默认 app）
  check [--no-front] [--e2e]
                         质量门禁（ruff/mypy/pytest/迁移/配置语法/文档漂移自查/前端 ESLint+vue-tsc；--no-front 跳过前端；
                         --e2e 追加真实链路冒烟，需先 up）
  e2e                    端到端冒烟：对**已运行**的容器跑登录 → 建文章 → 导出（临时数据自动清理）
  install-hooks          启用仓库 git 钩子（pre-push 会跑上面这条 check）
  export [--out 文件]    导出离线镜像包（4 镜像 → tar + .sha256）
                         省略 --out 时用 ~/my_blog_images/my_blog_images_<架构>_<时间戳>.tar
  import [--in 文件]     目标机：校验 → 加载镜像 → 重建容器 → 健康检查（绝不 --build）
  seed-media             把本机 media/ 同步进媒体卷（数据迁移用）
  seed-demo [--count N]  生成并导入演示游记（含 Markdown 正文与压缩插图，默认 30 篇）
  backup [--out 文件]    备份 SQLite 数据库（热备 + 完整性校验）
                         省略 --out 时用 ~/my_blog_backups/my_blog_db_<时间戳>.sqlite3
                         恢复步骤见 docs/BACKUP_RESTORE.md
  purge                  清理归档过期产物 + 悬空镜像
  help                   显示本帮助

引擎：自动识别 docker compose(v2) / docker-compose(v1) / podman-compose / podman compose，
      也可用 BLOG_ENGINE=docker|podman 强制指定（docker 需 daemon 可达）。

说明：涉及"镜像已变"的操作一律 down + up —— podman-compose 不会因镜像变更重建已存在
     的容器（它只比较镜像名）；docker compose 会重建，统一走 down+up 更省心。
EOF
}

main() {
  local cmd="${1:-help}"
  shift || true
  case "$cmd" in
    preflight)   cmd_preflight "$@" ;;
    up)          cmd_up "$@" ;;
    down)        cmd_down "$@" ;;
    restart)     cmd_restart "$@" ;;
    status)      cmd_status "$@" ;;
    logs)        cmd_logs "$@" ;;
    check)       cmd_check "$@" ;;
    e2e)         cmd_e2e "$@" ;;
    install-hooks) cmd_install_hooks "$@" ;;
    export)      cmd_export "$@" ;;
    import)      cmd_import "$@" ;;
    seed-media)  cmd_seed_media "$@" ;;
    seed-demo)   cmd_seed_demo "$@" ;;
    backup)      cmd_backup "$@" ;;
    purge)       cmd_purge "$@" ;;
    help|-h|--help) usage ;;
    *) fail "未知子命令：$cmd"; echo; usage; exit 1 ;;
  esac
}

main "$@"
