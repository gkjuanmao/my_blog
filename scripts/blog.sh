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
#   check [--front]      质量门禁（ruff/mypy/pytest/迁移检查/配置语法；--front 加前端类型检查）
#   export [--out 文件]  导出离线镜像包（4 镜像 → tar + .sha256）
#   import [--in 文件]   目标机：校验 → 加载镜像 → 重建容器 → 健康检查（绝不 --build）
#   seed-demo [--count N] 生成并导入演示游记（走真实导入链路）
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
BASE_URL="http://127.0.0.1:${NGINX_PORT}"
APP_CONTAINER="my_blog_app_1"
IMAGES=(
  "localhost/my_blog_app:latest"
  "localhost/my_blog_front:latest"
  "docker.io/library/nginx:1.27"
  "docker.io/library/redis:7-alpine"
)
HEALTH_PATHS=("/" "/api/v1/articles/" "/api/v1/docs")
EXPORT_DIR_DEFAULT="${HOME}/my_blog_images"
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
COMPOSE_CMD=()
detect_compose() {
  if command -v podman-compose >/dev/null 2>&1; then
    COMPOSE_CMD=(podman-compose)
  elif command -v podman >/dev/null 2>&1 && podman compose version >/dev/null 2>&1; then
    COMPOSE_CMD=(podman compose)
  else
    return 1
  fi
  return 0
}
compose() { "${COMPOSE_CMD[@]}" "$@"; }

require_tools() {
  command -v podman >/dev/null 2>&1 || die "未找到 podman" "Fedora: sudo dnf install -y podman podman-compose"
  detect_compose || die "未找到 compose 前端（podman-compose）" "Fedora: sudo dnf install -y podman-compose"
  command -v curl >/dev/null 2>&1 || die "未找到 curl" "Fedora: sudo dnf install -y curl"
}

# 从 .env 读取某个键（不 source，避免执行任意代码）
env_value() {
  [ -f .env ] || return 1
  local value
  value="$(sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" .env | tail -1)"
  value="${value%$'
'}"                     # 去 CR（Windows 行尾）
  value="${value#\"}"; value="${value%\"}"    # 去双引号
  value="${value#\'}"; value="${value%\'}"    # 去单引号
  printf '%s' "$value"
}

check_env_file() {
  [ -f .env ] || die "缺少 .env（compose 的 env_file 必需）" "cp .env.example .env 后按需修改"
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
  hint "诊断：podman logs ${APP_CONTAINER} | tail -30"
  hint "      podman logs my_blog_nginx_1 | tail -20"
  return 1
}

containers_running() {
  [ -n "$(podman ps --filter "name=${PROJECT}_" --format '{{.Names}}' 2>/dev/null)" ]
}
containers_exist() {
  [ -n "$(podman ps -a --filter "name=${PROJECT}_" --format '{{.Names}}' 2>/dev/null)" ]
}

# 校验容器实际使用的镜像 == latest（防止 podman-compose 复用旧镜像）
verify_container_image() {
  local container="$1" image="$2" cid iid
  cid="$(podman inspect "$container" --format '{{.Image}}' 2>/dev/null || true)"
  iid="$(podman image inspect "$image" --format '{{.Id}}' 2>/dev/null || true)"
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
  step "podman / compose"
  require_tools
  ok "podman $(podman --version | awk '{print $3}') · ${COMPOSE_CMD[*]}"

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
    warn "缺少 .env（up 之前需要：cp .env.example .env）"
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
    ok "app $(podman image inspect localhost/my_blog_app:latest --format '{{.Size}}' | awk '{printf "%.0fMB", $1/1024/1024}') · front $(podman image inspect localhost/my_blog_front:latest --format '{{.Size}}' | awk '{printf "%.0fMB", $1/1024/1024}')"
  fi

  step "重建容器"
  # 必须先 down：podman-compose up 只比较镜像名，改过 Dockerfile/依赖也要重建
  if containers_exist; then
    compose down >/dev/null 2>&1 || true
  fi
  compose up -d >/dev/null 2>&1 || die "容器启动失败" "podman-compose up -d  # 看完整输出"
  verify_container_image "$APP_CONTAINER" "localhost/my_blog_app:latest"
  ok "已按最新镜像重建"

  step "等待就绪"
  wait_ready

  step "健康检查"
  health_check || die "健康检查未全部通过" "podman logs ${APP_CONTAINER} | tail -30"
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
    podman volume ls --format '{{.Name}}' | grep "^${PROJECT}_" | sed 's/^/  - /'
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
  podman ps -a --filter "name=${PROJECT}_" --format '  {{.Names}}\t{{.Status}}\t{{.Image}}' || true

  title "镜像"
  local total=0 size
  for img in "${IMAGES[@]}"; do
    if podman image exists "$img"; then
      size="$(podman image inspect "$img" --format '{{.Size}}' 2>/dev/null || echo 0)"
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
  if podman ps --filter "name=${APP_CONTAINER}" --format '{{.Names}}' | grep -q .; then
    podman exec "$APP_CONTAINER" sh -c '
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
  local container="${PROJECT}_${svc}_1"
  podman ps -a --format '{{.Names}}' | grep -qx "$container" \
    || die "容器 $container 不存在" "先执行 scripts/blog.sh up"
  # shellcheck disable=SC2086
  podman logs $follow "$container"
}

# --------------------------------------------------------------------------- check
cmd_check() {
  local with_front=0
  for arg in "$@"; do [ "$arg" = "--front" ] && with_front=1; done
  command -v uv >/dev/null 2>&1 || die "未找到 uv" "https://docs.astral.sh/uv/"
  mkdir -p db_data
  title "质量门禁"
  run_show "ruff" uv run --frozen ruff check .
  run_show "mypy" uv run --frozen mypy config articles common users
  run_show_tail "pytest" 3 uv run --frozen pytest -q
  step "迁移一致性"; uv run --frozen python manage.py makemigrations --check --dry-run >/dev/null 2>&1 \
                       || die "存在未生成的迁移" "uv run python manage.py makemigrations"; ok
  block_step "配置语法"
  python3 -c "import yaml;yaml.safe_load(open('docker-compose.yml'))" || die "compose YAML 错误"
  sh -n docker/entrypoint.sh || die "docker/entrypoint.sh 语法错误"
  bash -n scripts/blog.sh || die "scripts/blog.sh 语法错误"
  if podman image exists docker.io/library/nginx:1.27; then
    podman run --rm --add-host app:127.0.0.1 --add-host front:127.0.0.1 \
      -v "$ROOT_DIR/docker/nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro,z" \
      docker.io/library/nginx:1.27 nginx -t >/dev/null 2>&1 || die "nginx.conf 语法错误"
  else
    warn "未找到 nginx 镜像，跳过 nginx -t"
  fi
  ok

  if [ "$with_front" = "1" ]; then
    step "前端类型检查（vue-tsc）"
    if containers_running; then
      warn "检测到本项目容器在运行；vue-tsc 会重写 front/.nuxt，与 nuxt dev 冲突"
    fi
    (cd front && npx --no-install vue-tsc --noEmit -p .nuxt/tsconfig.json 2>/dev/null \
      || npx vue-tsc --noEmit -p .nuxt/tsconfig.json) || die "vue-tsc 未通过"
    ok
  else
    hint "（前端类型检查默认跳过；需要时用 scripts/blog.sh check --front）"
  fi
}

# --------------------------------------------------------------------------- export / import
cmd_export() {
  local out=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --out) out="${2:-}"; shift 2 ;;
      *) die "未知参数：$1" ;;
    esac
  done
  require_tools
  [ -n "$out" ] || out="${EXPORT_DIR_DEFAULT}/my_blog_images_$(norm_arch)_$(date +%Y%m%d).tar"

  title "导出离线镜像包"
  step "校验镜像"
  local img
  for img in "${IMAGES[@]}"; do
    podman image exists "$img" || die "镜像缺失：$img" "先执行 scripts/blog.sh up --build"
  done
  ok "${#IMAGES[@]} 个镜像齐备"

  mkdir -p "$(dirname "$out")"
  block_step "打包"
  if ! podman save --format docker-archive -m -o "$out" "${IMAGES[@]}" 2>&1 | sed 's/^/    /'; then
    die "podman save 失败"
  fi
  sha256sum "$out" | awk '{print $1}' > "${out}.sha256"
  ok "$(human_size "$(stat -c%s "$out")")"

  step "校验和"
  ok "$(cat "${out}.sha256")"
  printf '\n产物：%s%s%s\n' "$C_BOLD" "$out" "$C_END"
  printf '  目标机：podman load -i %s\n' "$(basename "$out")"
  printf '  或直接：scripts/blog.sh import --in %s\n' "$out"
}

cmd_import() {
  local in="" yes=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --in) in="${2:-}"; shift 2 ;;
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
    expect="$(cat "${in}.sha256")"
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
  podman load -i "$in" >/dev/null 2>&1 || die "podman load 失败"
  local img
  for img in "${IMAGES[@]}"; do
    podman image exists "$img" || die "加载后仍缺镜像：$img"
  done
  ok "${#IMAGES[@]} 个镜像已就绪"

  step "环境变量"
  check_env_file
  ok ".env 就绪"

  step "重建容器（不使用 --build，直接用已加载镜像）"
  if containers_exist; then compose down >/dev/null 2>&1 || true; fi
  compose build >/dev/null 2>&1 || true   # 仅在镜像缺失时会真正构建；此处镜像已存在
  compose up -d >/dev/null 2>&1 || die "容器启动失败" "podman-compose up -d"
  verify_container_image "$APP_CONTAINER" "localhost/my_blog_app:latest"
  ok

  step "等待就绪"; wait_ready
  step "健康检查"; health_check || die "健康检查未通过" "podman logs ${APP_CONTAINER} | tail -30"
  printf '\n%s部署完成%s → %s%s/%s\n' "$C_OK" "$C_END" "$C_BOLD" "$BASE_URL" "$C_END"
  if [ "$yes" != "1" ] && [ -d media ] && [ "$(ls -A media/covers 2>/dev/null | wc -l)" -gt 0 ]; then
    hint "提示：若要让文章封面/附件可见，需把 media/ 同步进媒体卷：scripts/blog.sh seed-media"
  fi
}

# --------------------------------------------------------------------------- seed-media / seed-demo / purge
cmd_seed_media() {
  require_tools
  podman ps --filter "name=${APP_CONTAINER}" --format '{{.Names}}' | grep -q . \
    || die "app 容器未运行" "先执行 scripts/blog.sh up"
  [ -d media ] || die "本机没有 media/ 目录"
  title "把宿主机 media/ 同步进媒体卷"
  local n_covers n_files
  n_covers="$(ls -A media/covers 2>/dev/null | wc -l)"
  n_files="$(ls -A media/files 2>/dev/null | wc -l)"
  printf '  本机：covers %s 个 / files %s 个\n' "$n_covers" "$n_files"
  [ "$n_covers" -gt 0 ] || warn "media/covers 为空，跳过"
  podman cp media/. "${APP_CONTAINER}:/app/media/" || die "podman cp 失败"
  printf '  容器内：covers %s 个 / files %s 个\n' \
    "$(podman exec "$APP_CONTAINER" sh -c 'ls -A /app/media/covers | wc -l')" \
    "$(podman exec "$APP_CONTAINER" sh -c 'ls -A /app/media/files | wc -l')"
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
  podman ps --filter "name=${APP_CONTAINER}" --format '{{.Names}}' | grep -q . \
    || die "app 容器未运行" "先执行 scripts/blog.sh up"

  title "生成并导入演示游记"
  step "生成归档包（容器内）"
  local gen_args="--out /tmp/seed_demo.zip"
  [ -n "$count" ] && gen_args="$gen_args --count $count"
  # shellcheck disable=SC2086
  podman exec "$APP_CONTAINER" python /app/scripts/seed_demo.py $gen_args | sed 's/^/  /'
  podman cp "${APP_CONTAINER}:/tmp/seed_demo.zip" /tmp/seed_demo.zip >/dev/null
  ok "$(human_size "$(stat -c%s /tmp/seed_demo.zip)")"

  step "取管理员令牌"
  local token
  token="$(podman exec "$APP_CONTAINER" python -c "
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
  if podman ps --filter "name=${APP_CONTAINER}" --format '{{.Names}}' | grep -q .; then
    podman exec "$APP_CONTAINER" python manage.py purge_archives 2>/dev/null | tail -1 | sed 's/^/  /'
    ok
  else
    warn "app 容器未运行，跳过"
  fi
  step "悬空镜像"
  podman image prune -f >/dev/null 2>&1 || true
  ok "当前悬空镜像 $(podman images --filter dangling=true -q | wc -l) 个"
}

# --------------------------------------------------------------------------- 入口
usage() {
  cat <<'EOF'
用法：scripts/blog.sh <子命令> [选项]

  preflight              环境体检（podman/compose/架构/SELinux/端口/磁盘/配置语法）
  up [--build]           构建（可选）→ 重建容器 → 等待就绪 → 健康检查
  down [--purge]         停止容器（--purge 连数据卷一起删，需确认）
  restart [--build]      等价于 down + up
  status                 容器/镜像/端口/健康/归档产物/磁盘 一览
  logs [服务] [-f]       查看日志（app|nginx|front|redis，默认 app）
  check [--front]        质量门禁（ruff/mypy/pytest/迁移/配置语法；--front 加前端类型检查）
  export [--out 文件]    导出离线镜像包（4 镜像 → tar + .sha256）
  import [--in 文件]     目标机：校验 → 加载镜像 → 重建容器 → 健康检查（绝不 --build）
  seed-media             把本机 media/ 同步进媒体卷（数据迁移用）
  seed-demo [--count N]  生成并导入演示游记（走真实导入链路）
  purge                  清理归档过期产物 + 悬空镜像
  help                   显示本帮助

说明：涉及"镜像已变"的操作一律 down + up —— podman-compose 不会因镜像变更
     重建已存在的容器（它只比较镜像名），这是本项目实测踩过的坑。
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
    export)      cmd_export "$@" ;;
    import)      cmd_import "$@" ;;
    seed-media)  cmd_seed_media "$@" ;;
    seed-demo)   cmd_seed_demo "$@" ;;
    purge)       cmd_purge "$@" ;;
    help|-h|--help) usage ;;
    *) fail "未知子命令：$cmd"; echo; usage; exit 1 ;;
  esac
}

main "$@"
