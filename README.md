# Bright Horizon Photo Extractor

A modern, multi-tenant web application and background scraper engine that extracts, decrypts, and organizes children's photo and video memories from the Bright Horizons parent portal.

---

## 🌟 Key Features

- **🌐 Modern Multi-Tenant Web Interface**: Sleek React + Vite frontend with real-time extraction progress, media gallery filtering, and inline video playback.
- **🔒 Encrypted Multi-Tenant Storage**: Tenant isolation with AES-256-GCM encrypted media state (`manifest.enc`) and PBKDF2-HMAC-SHA256 key derivation (`master_secret.bin` & `salt.bin`).
- **🤖 Headless Automation & MFA Verification**: Interactive web-based Multi-Factor Authentication (MFA) verification flow with volatile memory zero-disk clearing.
- **⚡ High-Performance Scraper Engine**: Parallel asset download pool with intelligent DOM timeframe ready state detection (`wait_for_month_feed_ready`).
- **🗄️ Single ZIP Archive Center**: Asynchronous ZIP archive builder with SHA-256 manifest content change hashing (automatically disables re-generation when up to date).
- **📡 Resumable Download Streaming**: Full HTTP Range request compliance (`HTTP 206 Partial Content`) for low-memory, pause/resume multi-gigabyte ZIP downloads.
- **🏷️ Automated Metadata Injection**: EXIF comment embedding in JPEGs and pure-Python `tEXt` chunk injection in PNGs, with file modification times aligned to 10:00 AM Eastern Time (EST/EDT).

---

## 🛠️ Architecture Overview

```text
📁 Repository Layout
├── backend/
│   ├── server.py              # FastAPI REST API (Auth, Media, Extraction, Archives)
│   ├── scraper_engine.py      # Playwright Scraper Job Queue & Worker Threading
│   ├── dom_parser.py          # Portal DOM Selectors, Timeframe Ready Checks & Link Sanitizer
│   ├── database.py            # TenantStorage Isolation & Encrypted Manifest Management
│   ├── security.py            # AES-GCM Key Derivation, JWT Auth & Secret Preservation
│   ├── archive_stream.py      # Asynchronous ZIP Generation & HTTP Range Streamer
│   └── thumbnail.py          # Photo & Video Frame Square Thumbnail Generator
├── frontend/
│   ├── src/components/       # React Views (Login, MFA Verification, Gallery, ArchiveManager)
│   └── package.json           # Frontend UI Dependencies & Build Metadata
├── scripts/
│   ├── bump_version.py        # Automated Version & Git Commit Hash Counter
│   └── verify_deployment.py   # Live Deployment HTTP Health Checker
├── docker-compose.yml         # Container Orchestration Spec (App + FlareSolverr)
└── Dockerfile                 # Multi-Stage Node + Python Production Container Build
```

---

## 🚀 Quick Start (Local Development)

### 1. Requirements & Prerequisites
- Python 3.11+
- Node.js 20+
- [`uv`](https://astral.sh/uv) package manager

### 2. Running Locally with `uv`

Install dependencies and start the backend FastAPI server:
```bash
# Install Playwright browser dependencies
uv run playwright install chromium

# Launch the FastAPI backend server (http://localhost:8000)
uv run uvicorn main:app --reload --port 8000
```

Start the React development server:
```bash
cd frontend
npm install
npm run dev
```

---

## 🐳 Docker Deployment

The application is deployed as a production Docker container behind FlareSolverr.

### 1. Build and Launch Containers
```bash
# Bump semantic versioning tag
python3 scripts/bump_version.py

# Build and start container services in background
docker compose build && docker compose up -d
```

### 2. Verify Live Deployment
```bash
python3 scripts/verify_deployment.py https://bears.ceoloide.com
```

---

## 🧪 Running Unit Tests

The backend test suite includes 170+ unit and integration tests covering DOM parsing, security isolation, pipeline stress, multi-tenant manifest concurrency, and archive creation:

```bash
uv run pytest backend/tests/
```

---

## 📄 License & Versioning

All rights reserved. Adheres to Semantic Versioning (`vX.Y.Z-b<BUILD>`).
