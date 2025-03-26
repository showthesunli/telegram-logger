# 构建阶段
FROM python:3.13-slim-bookworm AS builder

# 1. 安装系统依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 2. 安装特定版本的 uv
COPY --from=ghcr.io/astral-sh/uv:0.6.9 /uv /uvx /bin/

# 3. 设置工作目录
WORKDIR /app

# 4. 先只复制依赖管理文件
COPY pyproject.toml uv.lock ./

# 5. 创建虚拟环境并安装依赖
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv && \
    . .venv/bin/activate && \
    uv pip install --no-deps -e .

# 6. 复制剩余代码
COPY . .

# 7. 完整安装并编译字节码
RUN --mount=type=cache,target=/root/.cache/uv \
    . .venv/bin/activate && \
    uv sync --frozen --compile-bytecode

# 运行时阶段
FROM python:3.13-slim-bookworm

# 1. 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH="/app/.venv/bin:$PATH" \
    UV_CACHE_DIR=/tmp/uv-cache

# 2. 从构建阶段复制虚拟环境
COPY --from=builder /app /app

# 3. 设置工作目录
WORKDIR /app

# 4. 添加元数据标签
LABEL org.opencontainers.image.source="https://github.com/username/telegram-delete-logger" \
    org.opencontainers.image.description="Telegram Delete Logger" \
    org.opencontainers.image.licenses="MIT"

# 5. 健康检查
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0 if __import__('os').path.exists('/app/.venv') else 1)"

# 6. 运行程序
CMD ["python", "main.py"]



