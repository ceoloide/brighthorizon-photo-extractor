# SPDX-License-Identifier: MIT
# FastAPI Server for Multi-Tenant Headless Bright Horizons Extractor
import os
import threading
from typing import Dict, Any, Optional
from fastapi import FastAPI, Depends, HTTPException, Header, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.security import verify_jwt_token, create_jwt_token, get_tenant_id
from backend.database import TenantStorage
from backend.scraper_engine import ScraperJob
from backend.archive_stream import start_zip_task, get_archive_status, range_stream_response

app = FastAPI(title="Bright Horizons Photo Extractor API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_active_jobs: Dict[str, ScraperJob] = {}

class LoginRequest(BaseModel):
    email: str
    password: str

class ExtractionRequest(BaseModel):
    sync_mode: str = "incremental" # "incremental" or "full"
    layout_mode: str = "flat"      # "flat" or "nested"
    child: str = "all"
    password: Optional[str] = None

class ArchiveRequest(BaseModel):
    layout_mode: str = "flat"

def get_current_tenant(authorization: Optional[str] = Header(None)) -> TenantStorage:
    """Dependency enforcing JWT authentication and multi-tenant scoping."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    
    token = authorization.split(" ")[1]
    payload = verify_jwt_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired session token")
    
    email = payload.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Invalid payload in token")
        
    return TenantStorage(email)

# --- Authentication Endpoints ---
@app.post("/api/auth/login")
def login(req: LoginRequest):
    email = req.email.strip().lower()
    if not email or not req.password:
        raise HTTPException(status_code=400, detail="Email and password are required")
        
    tenant_storage = TenantStorage(email)
    config = tenant_storage.load_config()
    config["email"] = email
    config["password"] = req.password # Note: config encrypted at rest via AES-256-GCM
    tenant_storage.save_config(config)
    
    token = create_jwt_token(email, tenant_storage.tenant_id)
    return {
        "status": "success",
        "token": token,
        "email": email,
        "tenant_id": tenant_storage.tenant_id,
        "children": config.get("children", [])
    }

@app.get("/api/auth/me")
def me(tenant: TenantStorage = Depends(get_current_tenant)):
    config = tenant.load_config()
    return {
        "email": tenant.email,
        "tenant_id": tenant.tenant_id,
        "children": config.get("children", []),
        "last_sync": config.get("last_sync")
    }

# --- Extraction Management ---
@app.post("/api/extraction/start")
def start_extraction(req: ExtractionRequest, tenant: TenantStorage = Depends(get_current_tenant)):
    tenant_id = tenant.tenant_id
    
    if tenant_id in _active_jobs and _active_jobs[tenant_id].status["state"] == "running":
        return {"status": "already_running", "job": _active_jobs[tenant_id].status}
        
    config = tenant.load_config()
    pwd = req.password or config.get("password")
    if not pwd:
        raise HTTPException(status_code=400, detail="Password is required to start extraction")
        
    options = {
        "sync_mode": req.sync_mode,
        "layout_mode": req.layout_mode,
        "child": req.child
    }
    
    job = ScraperJob(tenant, pwd, options)
    _active_jobs[tenant_id] = job
    
    thread = threading.Thread(target=job.run, daemon=True)
    thread.start()
    
    return {"status": "started", "job": job.status}

@app.get("/api/extraction/status")
def extraction_status(tenant: TenantStorage = Depends(get_current_tenant)):
    tenant_id = tenant.tenant_id
    if tenant_id in _active_jobs:
        return _active_jobs[tenant_id].status
    return {
        "state": "idle",
        "current_step": "No extraction active",
        "files_downloaded": 0,
        "error": None,
        "logs": []
    }

# --- Media Gallery & Direct File Streaming ---
@app.get("/api/media")
def list_media(tenant: TenantStorage = Depends(get_current_tenant)):
    manifest = tenant.load_manifest()
    items = list(manifest.values())
    # Sort descending by date
    items.sort(key=lambda x: x.get("date", ""), reverse=True)
    return {"status": "success", "count": len(items), "media": items}

@app.get("/api/media/{media_id}")
def get_media(media_id: str, token: Optional[str] = None, authorization: Optional[str] = Header(None)):
    # Support token in query string for <img> tags
    auth_token = token
    if not auth_token and authorization and authorization.startswith("Bearer "):
        auth_token = authorization.split(" ")[1]
        
    if not auth_token:
        raise HTTPException(status_code=401, detail="Authentication token required")
        
    payload = verify_jwt_token(auth_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
        
    tenant = TenantStorage(payload["email"])
    file_info = tenant.get_media_file_path(media_id)
    
    if not file_info:
        raise HTTPException(status_code=404, detail="Media asset not found or unauthorized")
        
    abs_path, mime_type, orig_filename = file_info
    return FileResponse(abs_path, media_type=mime_type, filename=orig_filename)

# --- Archive & Resumable Downloads ---
@app.post("/api/archive/create")
def create_archive(req: ArchiveRequest, tenant: TenantStorage = Depends(get_current_tenant)):
    task = start_zip_task(tenant, req.layout_mode)
    return task

@app.get("/api/archive/status")
def archive_status(tenant: TenantStorage = Depends(get_current_tenant)):
    return get_archive_status(tenant.tenant_id)

@app.get("/api/archive/download")
def download_archive(request: Request, token: Optional[str] = None, authorization: Optional[str] = Header(None)):
    auth_token = token
    if not auth_token and authorization and authorization.startswith("Bearer "):
        auth_token = authorization.split(" ")[1]
        
    if not auth_token:
        raise HTTPException(status_code=401, detail="Authentication token required")
        
    payload = verify_jwt_token(auth_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
        
    tenant = TenantStorage(payload["email"])
    status_info = get_archive_status(tenant.tenant_id)
    
    if status_info["status"] != "ready" or not status_info.get("archive_id"):
        raise HTTPException(status_code=400, detail="Archive not ready for download. Please generate archive first.")
        
    zip_path = os.path.join(tenant.archives_dir, status_info["archive_id"])
    return range_stream_response(zip_path, request, media_type="application/zip", filename=status_info["archive_id"])

# Serve frontend static files
dist_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"))
if os.path.exists(dist_dir):
    app.mount("/assets", StaticFiles(directory=os.path.join(dist_dir, "assets")), name="assets")
    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API endpoint not found")
        index_path = os.path.join(dist_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {"message": "Frontend build not found"}
