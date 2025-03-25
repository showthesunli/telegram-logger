# 构建阶段
FROM python:3.12-slim-bookworm AS builder

# 1. 安装系统依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 2. 安装uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 3. 设置工作目录
WORKDIR /app

# 4. 先只复制依赖管理文件
COPY pyproject.toml ./

# 5. 安装依赖
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --no-deps -e .

# 6. 复制剩余代码
COPY . .

# 7. 完整安装并编译字节码
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --compile-bytecode

# 运行时阶段
FROM python:3.12-slim-bookworm

# 1. 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH="/app/.venv/bin:$PATH" \
    UV_CACHE_DIR=/tmp/uv-cache

# 2. 从构建阶段复制虚拟环境
COPY --from=builder /app /app

# 3. 设置工作目录
WORKDIR /app

# 4. 运行程序
CMD ["uv", "run", "python", "-m", "telegram_logger.main"]
