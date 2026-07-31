# Stage 1: Build Frontend React Bundle
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# Stage 2: Production Python Runtime
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    DATA_DIR=/data

WORKDIR /app

# Install system dependencies & Playwright browser libraries
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
    && curl -sSL https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -o /tmp/chrome.deb \
    && apt-get install -y --no-install-recommends /tmp/chrome.deb \
    && rm /tmp/chrome.deb \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    fastapi uvicorn cryptography requests pydantic piexif playwright playwright-stealth \
    && playwright install chromium

# Copy application source & built frontend assets
COPY backend/ ./backend/
COPY main.py .
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

EXPOSE 8095

VOLUME ["/data"]

CMD ["uvicorn", "backend.server:app", "--host", "0.0.0.0", "--port", "8095"]
