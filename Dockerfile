FROM python:3.11

# Copy a current Node runtime for Vite 7 without relying on distro packages.
COPY --from=node:22-bookworm-slim /usr/local /usr/local

# 从 uv 官方镜像复制 uv
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

WORKDIR /app

ENV FLASK_DEBUG=false
ENV PYTHONUNBUFFERED=1
ENV PORT=5001

# 先复制依赖描述文件以利用缓存
COPY frontend/package.json frontend/package-lock.json ./frontend/
COPY backend/pyproject.toml backend/uv.lock ./backend/

# 安装依赖（Node + Python）
RUN npm ci --prefix frontend \
  && cd backend && uv sync --frozen --no-dev

# 复制项目源码
COPY . .

RUN npm --prefix frontend run build

EXPOSE 5001

CMD ["/app/backend/.venv/bin/python", "backend/run.py"]
