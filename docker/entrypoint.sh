#!/bin/sh
set -e

# 归档相关目录。注意：/bin/sh 在 python:3.12-slim 上是 dash，
# 不支持 `a/{b,c}` 花括号展开（会建出一个字面量目录名），必须逐个写。
# 目录创建是幂等的，worker 容器也要跑（它自己不 migrate，但要写这些目录）。
mkdir -p /app/tmp \
    /app/private_archives/staging \
    /app/private_archives/exports \
    /app/private_archives/rollbacks

# SKIP_MIGRATE=1 供 worker 容器使用：迁移与静态文件收集只能由 app 容器独占执行，
# 否则两个容器同时 migrate 会在 SQLite 上撞「table already exists」或写锁。
if [ "${SKIP_MIGRATE:-0}" = "1" ]; then
    echo "SKIP_MIGRATE=1：跳过 migrate / collectstatic / purge_archives（由 app 容器负责）"
    exec "$@"
fi

python manage.py migrate --noinput
python manage.py collectstatic --noinput

# 清理过期归档产物：进程被 SIGKILL 时视图里的 finally 不会执行，
# 所以除请求前的轻量清扫外，启动时也要兜一次底
python manage.py purge_archives || true

exec "$@"
