# SPDX-License-Identifier: MIT
# Async ZIP Archive Manager & HTTP Range Download Streamer
import os
import time
import zipfile
import threading
from typing import Dict, Any, Optional, Tuple
from fastapi import Request
from fastapi.responses import StreamingResponse
from backend.database import TenantStorage

_archive_tasks: Dict[str, Dict[str, Any]] = {}

def get_archive_status(tenant_id: str) -> Dict[str, Any]:
    """Returns current archive creation task status for a tenant."""
    return _archive_tasks.get(tenant_id, {
        "status": "idle",
        "progress_percent": 0.0,
        "archive_id": None,
        "file_size": 0,
        "created_at": None,
        "error": None
    })

def purge_previous_archives(archives_dir: str):
    """Purges all existing archive files for a tenant to ensure at most one archive file exists."""
    if os.path.exists(archives_dir):
        for fname in os.listdir(archives_dir):
            fpath = os.path.join(archives_dir, fname)
            if os.path.isfile(fpath):
                try:
                    os.remove(fpath)
                except Exception as e:
                    print(f"[Archive Purge Error] Failed to remove previous archive {fpath}: {e}")

def cancel_archive_task(tenant_id: str):
    """Cancels and purges any active or completed archive creation task for a tenant."""
    if tenant_id in _archive_tasks:
        task_info = _archive_tasks.pop(tenant_id, None)
        if task_info:
            task_info["cancelled"] = True
            task_info["status"] = "cancelled"
            task_info["error"] = "Account deleted"

def start_zip_task(tenant_storage: TenantStorage, layout: str = "flat") -> Dict[str, Any]:
    """Kicks off an asynchronous ZIP archive creation task in a background thread."""
    tenant_id = tenant_storage.tenant_id
    
    current_task = get_archive_status(tenant_id)
    if current_task["status"] == "processing":
        return current_task
    
    # Purge any previous archives to ensure at most a single archive exists per tenant
    purge_previous_archives(tenant_storage.archives_dir)

    task_info = {
        "status": "processing",
        "progress_percent": 0.0,
        "archive_id": f"archive_{int(time.time())}.zip",
        "file_size": 0,
        "created_at": int(time.time()),
        "cancelled": False,
        "error": None
    }
    _archive_tasks[tenant_id] = task_info
    
    def worker():
        try:
            manifest = tenant_storage.load_manifest()
            total_files = len(manifest)
            if total_files == 0:
                task_info["status"] = "error"
                task_info["error"] = "No media files found to archive."
                return
            
            target_zip_path = os.path.join(tenant_storage.archives_dir, task_info["archive_id"])
            
            with zipfile.ZipFile(target_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                processed = 0
                used_arcnames = set()
                tenant_dir_abs = os.path.abspath(tenant_storage.tenant_dir)
                
                for media_id, item in manifest.items():
                    if task_info.get("cancelled"):
                        print(f"[Archive Worker] Task cancelled for tenant {tenant_id}. Aborting ZIP creation.")
                        break

                    rel_path = item["storage_path"]
                    abs_src = os.path.abspath(os.path.join(tenant_storage.tenant_dir, rel_path))
                    
                    # Security: Enforce path traversal check
                    if not abs_src.startswith(tenant_dir_abs):
                        processed += 1
                        continue

                    if os.path.exists(abs_src):
                        child = item.get("child", "Child")
                        orig_name = item.get("original_filename", f"{media_id}.jpg")
                        year = item.get("year", "")
                        month = item.get("month", "")
                        
                        if layout == "nested" and year and month:
                            arcname = os.path.join(child, f"{year:04d}", f"{month:02d}", orig_name)
                        else:
                            arcname = os.path.join(child, orig_name)
                            
                        # Resolve filename collisions cleanly inside ZIP
                        if arcname in used_arcnames:
                            base, ext = os.path.splitext(arcname)
                            arcname = f"{base}_{media_id[:6]}{ext}"
                        used_arcnames.add(arcname)

                        zf.write(abs_src, arcname=arcname)
                    
                    processed += 1
                    task_info["progress_percent"] = round((processed / total_files) * 100.0, 1)

            if task_info.get("cancelled"):
                if os.path.exists(target_zip_path):
                    try: os.remove(target_zip_path)
                    except Exception: pass
                return
            
            task_info["status"] = "ready"
            task_info["file_size"] = os.path.getsize(target_zip_path)
            task_info["progress_percent"] = 100.0
        except Exception as e:
            if not task_info.get("cancelled"):
                task_info["status"] = "error"
                task_info["error"] = str(e)
            
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return task_info

def parse_range_header(range_header: str, file_size: int) -> Optional[Tuple[int, int]]:
    """Parses standard HTTP Range header (e.g. 'bytes=0-1023' or 'bytes=1024-')."""
    if not range_header or not range_header.startswith("bytes="):
        return None
    try:
        range_val = range_header[6:].strip()
        if "-" not in range_val:
            return None
        start_str, end_str = range_val.split("-", 1)
        
        start = int(start_str) if start_str else 0
        end = int(end_str) if end_str else file_size - 1
        
        if start >= file_size or start > end:
            return None
        
        end = min(end, file_size - 1)
        return start, end
    except Exception:
        return None

def range_stream_response(file_path: str, request: Request, media_type: str = "application/zip", filename: str = "download.zip"):
    """
    Returns a FastAPI StreamingResponse supporting HTTP Range requests for download resume.
    """
    if not os.path.exists(file_path):
        return StreamingResponse(iter([b"File not found"]), status_code=404)
        
    file_size = os.path.getsize(file_path)
    range_header = request.headers.get("range")
    range_bounds = parse_range_header(range_header, file_size)
    
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'attachment; filename="{filename}"'
    }
    
    if range_bounds:
        start, end = range_bounds
        content_length = (end - start) + 1
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        headers["Content-Length"] = str(content_length)
        
        def iterfile():
            with open(file_path, "rb") as f:
                f.seek(start)
                bytes_left = content_length
                chunk_size = 64 * 1024
                while bytes_left > 0:
                    read_len = min(chunk_size, bytes_left)
                    data = f.read(read_len)
                    if not data:
                        break
                    bytes_left -= len(data)
                    yield data
                    
        return StreamingResponse(iterfile(), status_code=206, headers=headers, media_type=media_type)
    else:
        headers["Content-Length"] = str(file_size)
        def iterfile_full():
            with open(file_path, "rb") as f:
                while chunk := f.read(64 * 1024):
                    yield chunk
        return StreamingResponse(iterfile_full(), status_code=200, headers=headers, media_type=media_type)
