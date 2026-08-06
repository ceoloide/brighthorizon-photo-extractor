# Stage 1: Build Frontend React Bundle
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend

# Cache npm dependencies layer
COPY frontend/package*.json ./
RUN npm install

# Copy frontend source and build dist
COPY frontend/ ./
RUN npm run build

# Stage 2: Production Python Runtime
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    DATA_DIR=/app/data

WORKDIR /app

# 1. System & Playwright dependencies (Cached OS Layer)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    xauth \
    xvfb \
    ffmpeg \
    && curl -sSL https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -o /tmp/chrome.deb \
    && apt-get install -y --no-install-recommends /tmp/chrome.deb \
    && rm /tmp/chrome.deb \
    && rm -rf /var/lib/apt/lists/*

# 2. Python package dependencies (Cached Pip Layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install chromium

# 3. Frontend Dist Bundle (Cached Frontend Layer)
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# 4. Application Source Code (Fast-changing App Layer - builds instantly)
COPY backend/ ./backend/
COPY version.json .
COPY main.py .

EXPOSE 8095
VOLUME ["/app/data"]

CMD ["uvicorn", "backend.server:app", "--host", "0.0.0.0", "--port", "8095"]

