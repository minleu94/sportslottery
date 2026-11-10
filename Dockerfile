# Stage 1: Build React Frontend
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci --prefer-offline --no-audit

COPY frontend/ ./
RUN npm run build

# Stage 2: Python Backend Runtime
FROM python:3.11-slim
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8100 \
    SPORTSLOTTERY_WORKSPACE=/app

# System dependencies for scientific packages and git
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-lock.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    (pip install --no-cache-dir -r requirements-lock.txt || pip install --no-cache-dir -r requirements.txt)

# Copy application source
COPY . /app

# Copy compiled frontend from builder
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Ensure local data directory structure exists
RUN mkdir -p /app/data/cache /app/data/snapshots /app/data/logs

EXPOSE 8100

CMD ["python", "-m", "uvicorn", "server.api:app", "--host", "0.0.0.0", "--port", "8100"]
