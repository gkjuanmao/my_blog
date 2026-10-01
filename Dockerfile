# =============================================================================
# 构建阶段：只负责“装依赖”，产物不会进入最终镜像
# =============================================================================
FROM python:3.12-slim AS builder

# 依赖装进独立 venv，便于整体拷进运行阶段
ENV UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

# 构建期（若某个依赖没有预编译 wheel）可能需要编译器；本层不会进入最终镜像
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g; s|security.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.m.daocloud.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
# 仓库里的 uv.lock 已指向清华 TUNA 镜像源，**不需要**构建期再改源；
# `--frozen` 保证只用 lock 里锁定的版本（不会重新解析）。
RUN uv sync --frozen --no-dev

# =============================================================================
# 运行阶段：只带 venv + 源码（不带编译器、不带 uv，约省 370MB）
# =============================================================================
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# venv 在构建阶段与本阶段路径一致（/opt/venv），因此软链与 shebang 都能直接用
COPY --from=builder /opt/venv /opt/venv
COPY . .

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
# gthread + 多 worker：单 worker（gunicorn 默认）时一次归档导入/导出会阻塞整站，
# 而 nginx 默认 proxy_read_timeout 60s 会把排队的公共请求变成 504。
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", \
     "--worker-class", "gthread", "--workers", "3", "--threads", "4", \
     "--timeout", "120", "--graceful-timeout", "30"]
