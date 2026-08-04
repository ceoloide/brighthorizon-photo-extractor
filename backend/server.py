# SPDX-License-Identifier: MIT
# FastAPI Server for Multi-Tenant Headless Bright Horizons Extractor
import os
import time
import json
import asyncio
import threading
from datetime import datetime
from typing import Dict, Any, Optional
from urllib.parse import quote
from fastapi import FastAPI, Depends, HTTPException, Header, Request, status, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.security import verify_jwt_token, create_jwt_token, get_tenant_id
from backend.database import TenantStorage
from backend.scraper_engine import ScraperJob, redownload_single_media_item
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

class MfaRequest(BaseModel):
    email: str
    code: str

class ExtractionRequest(BaseModel):
    sync_mode: str = "incremental" # "incremental", "full", or "custom"
    start_date: Optional[str] = None # "YYYY-MM-DD"
    child: str = "all"
    force: bool = False
    password: Optional[str] = None

class ArchiveRequest(BaseModel):
    layout_mode: str = "flat"

def parse_unix_timestamp(ts: Any) -> Optional[float]:
    """Parses a timestamp that may be in seconds (10 digits) or milliseconds (13 digits)."""
    try:
        val = float(ts)
        if val > 1e11:
            return val / 1000.0
        return val
    except Exception:
        return None

def get_current_tenant(
    request: Request,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None)
) -> TenantStorage:
    """Dependency enforcing JWT authentication via Bearer token, query param, or HTTP cookie."""
    jwt_str = None
    
    if authorization and authorization.startswith("Bearer "):
        jwt_str = authorization.split(" ")[1]
        
    if not jwt_str and token:
        jwt_str = token
        
    if not jwt_str or jwt_str.startswith("device_session_"):
        jwt_str = request.cookies.get("bh_tenant_token")
        
    if jwt_str:
        payload = verify_jwt_token(jwt_str)
        if payload and payload.get("email"):
            return TenantStorage(payload["email"])
            
    cookie_token = request.cookies.get("bh_tenant_token")
    if cookie_token:
        payload = verify_jwt_token(cookie_token)
        if payload and payload.get("email"):
            return TenantStorage(payload["email"])
            
    raise HTTPException(status_code=401, detail="Authentication required or session expired.")

_active_verifications: Dict[str, Dict[str, Any]] = {}

def _start_verification_thread(email: str, password: str, tenant_storage: TenantStorage) -> Dict[str, Any]:
    tenant_id = tenant_storage.tenant_id
    if tenant_id in _active_jobs and _active_jobs[tenant_id].status.get("state") == "running":
        raise HTTPException(
            status_code=409,
            detail="An extraction job is currently running for this account. Re-authentication is blocked to protect the active extraction job."
        )
    state = {
        "status": "running",
        "step": "Starting headless browser & Cloudflare challenge check...",
        "step_index": 1,
        "screenshot": None,
        "children": [],
        "error": None,
        "timestamp": time.time()
    }
    _active_verifications[tenant_id] = state
    
    def run_verification():
        job = ScraperJob(tenant_storage, password, {})
        state["job"] = job
        def on_progress(p):
            state["step"] = p.get("step", "")
            state["step_index"] = p.get("step_index", 1)
            state["timestamp"] = time.time()
            if job.status.get("state") == "mfa_required":
                state["status"] = "mfa_required"
            elif state.get("status") == "mfa_required" and job.status.get("state") == "running":
                state["status"] = "running"
            if p.get("screenshot"):
                state["screenshot"] = p.get("screenshot")
                
        try:
            children = job.verify_credentials(progress_callback=on_progress)
            config = tenant_storage.load_config()
            config["email"] = email
            config["password"] = password
            config["children"] = children
            tenant_storage.save_config(config)
            
            session_expires_at = config.get("session_expires_at") or int((time.time() + 900) * 1000)
            token = create_jwt_token(email, tenant_id)
            state["status"] = "success"
            state["token"] = token
            state["email"] = email
            state["children"] = children
            state["session_expires_at"] = session_expires_at
            state["step"] = "Verification complete!"
            state["timestamp"] = time.time()
        except Exception as e:
            state["status"] = "failed"
            state["error"] = str(e)
            state["timestamp"] = time.time()
        finally:
            def schedule_cleanup():
                time.sleep(300) # Retain verification session state & live preview screenshot for 5 minutes
            threading.Thread(target=schedule_cleanup, daemon=True).start()
            
    t = threading.Thread(target=run_verification, daemon=True)
    t.start()
    return state

# --- Authentication Endpoints ---
@app.get("/api/auth/verify-stream")
async def verify_stream(email: str = Query(...), password: str = Query(...)):
    email_clean = email.strip().lower()
    if not email_clean or not password:
        raise HTTPException(status_code=400, detail="Email and password are required")
        
    tenant_storage = TenantStorage(email_clean)
    tenant_id = tenant_storage.tenant_id
    
    current_state = _active_verifications.get(tenant_id)
    if not current_state or current_state.get("status") in ["success", "failed", "completed_reset"]:
        _active_verifications.pop(tenant_id, None)
        current_state = _start_verification_thread(email_clean, password, tenant_storage)

    async def event_generator():
        while True:
            state = _active_verifications.get(tenant_id)
            if not state:
                break
            
            clean_state = {k: v for k, v in state.items() if k != "job"}
            payload = json.dumps(clean_state)
            yield f"data: {payload}\n\n"
            
            if state.get("status") in ["success", "failed"]:
                await asyncio.sleep(0.5)
                yield f"data: {json.dumps(clean_state)}\n\n"
                break
                
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@app.post("/api/auth/verify-progress")
def verify_progress(req: LoginRequest):
    email = req.email.strip().lower()
    if not email or not req.password:
        raise HTTPException(status_code=400, detail="Email and password are required")
        
    tenant_storage = TenantStorage(email)
    tenant_id = tenant_storage.tenant_id
    
    current_state = _active_verifications.get(tenant_id)
    if not current_state or current_state.get("status") in ["success", "failed", "completed_reset"]:
        _active_verifications.pop(tenant_id, None)
        current_state = _start_verification_thread(email, req.password, tenant_storage)
        return JSONResponse(content=current_state)
        
    return JSONResponse(content=current_state)

_mfa_attempts: Dict[str, int] = {}

@app.post("/api/auth/submit-mfa-code")
def submit_mfa_code(req: MfaRequest):
    email = req.email.strip().lower()
    code = req.code.strip()
    
    if not code.isdigit() or len(code) != 6:
        raise HTTPException(status_code=400, detail="Invalid 6-digit verification code format.")
        
    tenant_storage = TenantStorage(email)
    tenant_id = tenant_storage.tenant_id
    
    verification = _active_verifications.get(tenant_id)
    job = None
    if verification and "job" in verification:
        job = verification["job"]
    elif tenant_id in _active_jobs:
        job = _active_jobs[tenant_id]
        
    if not job:
        raise HTTPException(status_code=404, detail="No active login verification session found for this email.")
        
    attempts = _mfa_attempts.get(tenant_id, 0)
    if attempts >= 3:
        raise HTTPException(status_code=429, detail="Too many failed MFA verification attempts. Please restart login.")
        
    _mfa_attempts[tenant_id] = attempts + 1
    success = job.submit_mfa_code(code)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to submit MFA verification code.")
        
    _mfa_attempts.pop(tenant_id, None)
    return {"status": "success", "message": "Verification code received. Resuming authentication..."}

@app.post("/api/auth/logout")
def logout(response: Response, request: Request, authorization: Optional[str] = Header(None)):
    token = request.cookies.get("bh_tenant_token")
    if not token and authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        
    if token:
        payload = verify_jwt_token(token)
        if payload and "email" in payload:
            email = payload["email"]
            tenant = TenantStorage(email)
            tenant_id = tenant.tenant_id
            
            # Stop any running extraction job or live Playwright browser/screen session
            if tenant_id in _active_jobs:
                try:
                    job = _active_jobs.pop(tenant_id, None)
                    if job:
                        job.cancel()
                        print(f"[Logout] Cancelled running scraper job for tenant {tenant_id}")
                except Exception as e:
                    print(f"[Logout Error] Failed to cancel scraper job for tenant {tenant_id}: {e}")

            # Pop any verification session state from memory
            _active_verifications.pop(tenant_id, None)
                    
            # Clear server-side session cookies, storage_state.json, and browser profile
            tenant.clear_session()
            
    response.delete_cookie("bh_tenant_token")
    return {"status": "success", "message": "Signed out successfully, stopped browser sessions, cancelled running jobs, and cleared server cookies."}

@app.get("/api/auth/me")
def get_me(request: Request, authorization: Optional[str] = Header(None)):
    token = request.cookies.get("bh_tenant_token")
    if not token and authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        
    if not token:
        return {"authenticated": False}
        
    payload = verify_jwt_token(token)
    if not payload or "email" not in payload:
        return {"authenticated": False}
        
    tenant = TenantStorage(payload["email"])
    state_file = os.path.join(tenant.user_data_dir, "storage_state.json")
    if not os.path.exists(state_file):
        res = JSONResponse(content={"authenticated": False})
        res.delete_cookie("bh_tenant_token")
        return res

    config = tenant.load_config()
    session_expires_at = config.get("session_expires_at") or int((time.time() + 900) * 1000)
    
    return {
        "authenticated": True,
        "email": tenant.email,
        "tenant_id": tenant.tenant_id,
        "token": token,
        "children": config.get("children", []),
        "session_expires_at": session_expires_at,
        "last_sync": config.get("last_sync")
    }

@app.delete("/api/auth/delete-account")
def delete_account(tenant: TenantStorage = Depends(get_current_tenant)):
    tenant_id = tenant.tenant_id
    
    # Terminate active job if running
    if tenant_id in _active_jobs:
        job = _active_jobs.pop(tenant_id, None)
        if job:
            job.status["state"] = "failed"
            job.status["error"] = "Account deleted"

    # Pop any verification session state from memory
    _active_verifications.pop(tenant_id, None)
            
    # Purge all media, user_data, encrypted manifests, and archives from disk
    tenant.purge_all_data()
    
    return {
        "status": "success",
        "message": "Account and all associated media, manifests, and browser sessions have been permanently deleted."
    }


# --- Extraction Management ---
@app.post("/api/extraction/start")
def start_extraction(req: ExtractionRequest, tenant: TenantStorage = Depends(get_current_tenant)):
    tenant_id = tenant.tenant_id
    
    if tenant_id in _active_jobs and _active_jobs[tenant_id].status["state"] == "running":
        if not req.force:
            return JSONResponse(
                status_code=409,
                content={
                    "status": "running_conflict",
                    "message": "An extraction job is currently running.",
                    "job": _active_jobs[tenant_id].status
                }
            )
        else:
            old_job = _active_jobs.pop(tenant_id, None)
            if old_job:
                old_job.cancel()
                
    config = tenant.load_config()
    pwd = req.password or config.get("password") or "imported_session"
        
    options = {
        "sync_mode": req.sync_mode,
        "start_date": req.start_date,
        "layout_mode": "flat",
        "child": req.child
    }
    
    job = ScraperJob(tenant, pwd, options)
    _active_jobs[tenant_id] = job
    
    thread = threading.Thread(target=job.run, daemon=True)
    thread.start()
    
    return {"status": "started", "job": job.status}

@app.post("/api/extraction/cancel")
def cancel_extraction(tenant: TenantStorage = Depends(get_current_tenant)):
    tenant_id = tenant.tenant_id
    if tenant_id in _active_jobs:
        job = _active_jobs[tenant_id]
        job.cancel()
        return {"status": "cancelled", "message": "Extraction job cancellation requested."}
    return {"status": "idle", "message": "No active job running."}

@app.get("/api/extraction/events")
def extraction_events(tenant: TenantStorage = Depends(get_current_tenant)):
    tenant_id = tenant.tenant_id
    
    def event_generator():
        while True:
            job = _active_jobs.get(tenant_id)
            if job:
                st = job.status
                payload_str = json.dumps(st)
                yield f"data: {payload_str}\n\n"
                if st.get("state") in ["completed", "failed", "cancelled"]:
                    break
            else:
                payload_str = json.dumps({
                    "state": "idle",
                    "current_step": "No extraction active",
                    "files_downloaded": 0,
                    "error": None,
                    "logs": []
                })
                yield f"data: {payload_str}\n\n"
                break
            time.sleep(1.0)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

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
def serve_media(media_id: str, request: Request, token: Optional[str] = None, authorization: Optional[str] = Header(None), thumb: bool = False, thumbnail: bool = False):
    auth_token = token
    if not auth_token and authorization and authorization.startswith("Bearer "):
        auth_token = authorization.split(" ")[1]
        
    payload = verify_jwt_token(auth_token) if auth_token else None
    
    if not payload or not payload.get("email"):
        cookie_token = request.cookies.get("bh_tenant_token")
        if cookie_token:
            payload = verify_jwt_token(cookie_token)
            
    if payload and payload.get("email"):
        tenant = TenantStorage(payload["email"])
        if thumb or thumbnail:
            thumb_bytes = tenant.get_media_thumbnail_bytes(media_id)
            if thumb_bytes:
                return Response(content=thumb_bytes, media_type="image/jpeg")
        file_info = tenant.get_media_file_path(media_id)
        if file_info:
            abs_path, mime_type, orig_filename = file_info
            return FileResponse(abs_path, media_type=mime_type, filename=orig_filename)

    # Fallback for session/local dev mode: search tenant directories directly for media_id
    if os.path.exists(TENANTS_DIR):
        for tenant_folder in os.listdir(TENANTS_DIR):
            t_dir = os.path.join(TENANTS_DIR, tenant_folder)
            m_file = os.path.join(t_dir, "manifest.enc")
            if not os.path.exists(m_file):
                m_file = os.path.join(t_dir, "manifest.dat")
            if os.path.exists(m_file):
                try:
                    with open(m_file, "r") as f:
                        manifest = decrypt_json(f.read())
                    if media_id in manifest:
                        item = manifest[media_id]
                        if thumb or thumbnail:
                            tenant_obj = TenantStorage(tenant_folder)
                            thumb_bytes = tenant_obj.get_media_thumbnail_bytes(media_id)
                            if thumb_bytes:
                                return Response(content=thumb_bytes, media_type="image/jpeg")
                        rel_path = item.get("storage_path")
                        if rel_path:
                            abs_path = os.path.abspath(os.path.join(t_dir, rel_path))
                            if abs_path.startswith(os.path.abspath(t_dir)) and os.path.exists(abs_path):
                                return FileResponse(abs_path, media_type=item.get("mime_type", "image/jpeg"), filename=item.get("original_filename", "photo.jpg"))
                except Exception:
                    pass

    raise HTTPException(status_code=404, detail="Media asset not found or unauthorized")

@app.get("/api/media/{media_id}/thumbnail")
def serve_media_thumbnail(media_id: str, request: Request, token: Optional[str] = None, authorization: Optional[str] = Header(None)):
    return serve_media(media_id, request, token=token, authorization=authorization, thumb=True)

@app.post("/api/media/{media_id}/redownload")
def redownload_media_item_endpoint(media_id: str, tenant: TenantStorage = Depends(get_current_tenant)):
    try:
        updated_entry = redownload_single_media_item(tenant, media_id)
        return {"status": "success", "message": "Successfully re-downloaded media item from My Bright Day", "media": updated_entry}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
        file_path = os.path.join(dist_dir, full_path)
        if full_path and os.path.isfile(file_path):
            return FileResponse(file_path)
        index_path = os.path.join(dist_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path, headers={
                "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0"
            })
        return {"message": "Frontend build not found"}

