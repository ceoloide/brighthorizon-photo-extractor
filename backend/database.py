# SPDX-License-Identifier: MIT
# Tenant Database & Storage Manager for Bright Horizons Photo Extractor
import json
import os
import shutil
import threading
import uuid
from typing import Dict, Any, List, Optional, Tuple
from backend.security import get_tenant_id, encrypt_json, decrypt_json, DATA_DIR

class TenantStorage:
    def __init__(self, email: str):
        self.email = email.strip().lower()
        self.tenant_id = get_tenant_id(self.email)
        self.tenant_dir = os.path.join(DATA_DIR, "tenants", self.tenant_id)
        self.media_dir = os.path.join(self.tenant_dir, "media")
        self.archives_dir = os.path.join(self.tenant_dir, "archives")
        self.user_data_dir = os.path.join(self.tenant_dir, "user_data")
        self.logs_dir = os.path.join(self.tenant_dir, "logs")
        self.latest_log_file = os.path.join(self.logs_dir, "extraction.log")
        
        self.config_file = os.path.join(self.tenant_dir, "config.enc")
        self.manifest_file = os.path.join(self.tenant_dir, "manifest.enc")
        self._lock = threading.Lock()
        
        self._ensure_dirs()
        
    def _ensure_dirs(self):
        os.makedirs(self.tenant_dir, exist_ok=True)
        os.makedirs(self.media_dir, exist_ok=True)
        os.makedirs(self.archives_dir, exist_ok=True)
        os.makedirs(self.user_data_dir, exist_ok=True)
        os.makedirs(self.logs_dir, exist_ok=True)

    def append_log(self, entry_str: str):
        """Appends a log line to the persistent tenant log file on disk."""
        with self._lock:
            try:
                with open(self.latest_log_file, "a", encoding="utf-8") as f:
                    f.write(entry_str + "\n")
            except Exception:
                pass

    def clear_log(self):
        """Initializes/resets the persistent tenant log file for a new extraction run."""
        with self._lock:
            try:
                with open(self.latest_log_file, "w", encoding="utf-8") as f:
                    from datetime import datetime
                    f.write(f"--- Extraction Log Started: {datetime.now().isoformat()} ---\n")
            except Exception:
                pass

    def purge_all_data(self):
        """Completely purges all data for this tenant (media, manifests, user_data, archives)."""
        self.clear_session()
        if os.path.exists(self.tenant_dir):
            try:
                shutil.rmtree(self.tenant_dir, ignore_errors=True)
                print(f"[TenantStorage] Successfully purged all data for tenant {self.tenant_id}")
            except Exception as e:
                print(f"[TenantStorage Error] Purging tenant directory {self.tenant_id} failed: {e}")

    def clear_session(self):
        """Clears the tenant's browser user_data session and state file when expired or upon sign-off."""
        state_file = os.path.join(self.user_data_dir, "storage_state.json")
        if os.path.exists(state_file):
            try:
                os.remove(state_file)
                print(f"[TenantStorage] Deleted session state file for {self.tenant_id}")
            except Exception as e:
                print(f"[TenantStorage Error] Failed to delete session state file: {e}")
        if os.path.exists(self.user_data_dir):
            try:
                # Clean Singleton Lock files before rmtree
                for root, dirs, files in os.walk(self.user_data_dir):
                    for f in files:
                        if "Singleton" in f or "Lock" in f or "RunningChromeVersion" in f:
                            try:
                                os.remove(os.path.join(root, f))
                            except Exception:
                                pass
                shutil.rmtree(self.user_data_dir, ignore_errors=True)
                os.makedirs(self.user_data_dir, exist_ok=True)
                print(f"[TenantStorage] Purged user_data directory for {self.tenant_id}")
            except Exception as e:
                print(f"[TenantStorage Error] Failed to purge user_data_dir: {e}")

    # --- Config Management ---
    def load_config(self) -> Dict[str, Any]:
        """Loads tenant configuration (encrypted at rest)."""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r") as f:
                    return decrypt_json(f.read())
            except Exception as e:
                print(f"Error loading tenant config for {self.tenant_id}: {e}")
        return {
            "email": self.email,
            "children": [],
            "last_sync": None,
            "sync_status": "idle"
        }

    def save_config(self, config_data: Dict[str, Any]):
        """Saves tenant configuration encrypted at rest."""
        encrypted_str = encrypt_json(config_data)
        with open(self.config_file, "w") as f:
            f.write(encrypted_str)

    # --- Manifest & Media Management ---
    def load_manifest(self) -> Dict[str, Any]:
        """Loads the tenant's encrypted media manifest."""
        with self._lock:
            if os.path.exists(self.manifest_file):
                try:
                    with open(self.manifest_file, "r") as f:
                        return decrypt_json(f.read())
                except Exception as e:
                    print(f"Error loading manifest for {self.tenant_id}: {e}")
            return {}

    def save_manifest(self, manifest: Dict[str, Any]):
        """Saves tenant media manifest encrypted at rest."""
        with self._lock:
            encrypted_str = encrypt_json(manifest)
            with open(self.manifest_file, "w") as f:
                f.write(encrypted_str)

    def add_media_entry(self, obj_id: str, child: str, date_str: str, original_filename: str, comment: str, file_bytes: bytes, mime_type: str) -> Dict[str, Any]:
        """Saves media file to obfuscated storage path and updates encrypted manifest."""
        with self._lock:
            manifest = self._load_manifest_unlocked()
            
            # Check if obj_id already exists in manifest
            for m_id, item in manifest.items():
                if item.get("obj_id") == obj_id:
                    # Update existing file content/metadata
                    target_path = os.path.abspath(os.path.join(self.tenant_dir, item["storage_path"]))
                    if not target_path.startswith(os.path.abspath(self.tenant_dir)):
                        raise Exception("Security Error: Path traversal attempt detected")
                    with open(target_path, "wb") as f:
                        f.write(file_bytes)
                    item["file_size"] = len(file_bytes)
                    item["comment"] = comment
                    self._save_manifest_unlocked(manifest)
                    return item

            # New entry
            media_id = str(uuid.uuid4())
            rel_storage_path = os.path.join("media", f"{media_id}.dat")
            abs_storage_path = os.path.abspath(os.path.join(self.tenant_dir, rel_storage_path))
            
            if not abs_storage_path.startswith(os.path.abspath(self.tenant_dir)):
                raise Exception("Security Error: Path traversal attempt detected")
                
            with open(abs_storage_path, "wb") as f:
                f.write(file_bytes)

            # Generate & save 400x400 square thumbnail
            is_vid = mime_type.startswith("video") or original_filename.lower().endswith((".mp4", ".mov", ".avi", ".mkv", ".webm"))
            rel_thumb_path = os.path.join("media", f"{media_id}_thumb.dat")
            abs_thumb_path = os.path.abspath(os.path.join(self.tenant_dir, rel_thumb_path))
            try:
                from backend.thumbnail import generate_square_thumbnail
                thumb_bytes = generate_square_thumbnail(file_bytes, is_video=is_vid)
                if thumb_bytes:
                    with open(abs_thumb_path, "wb") as tf:
                        tf.write(thumb_bytes)
            except Exception as e:
                print(f"[Thumbnail Notice] Error generating thumbnail on save for {media_id}: {e}")
                
            entry = {
                "media_id": media_id,
                "obj_id": obj_id,
                "child": child,
                "date": date_str,
                "year": int(date_str.split("-")[0]) if "-" in date_str else None,
                "month": int(date_str.split("-")[1]) if "-" in date_str and len(date_str.split("-")) > 1 else None,
                "original_filename": original_filename,
                "comment": comment,
                "mime_type": mime_type,
                "file_size": len(file_bytes),
                "storage_path": rel_storage_path,
                "thumb_path": rel_thumb_path
            }
            manifest[media_id] = entry
            self._save_manifest_unlocked(manifest)
            return entry

    def _load_manifest_unlocked(self) -> Dict[str, Any]:
        if os.path.exists(self.manifest_file):
            try:
                with open(self.manifest_file, "r") as f:
                    return decrypt_json(f.read())
            except Exception as e:
                print(f"Error loading manifest for {self.tenant_id}: {e}")
        return {}

    def _save_manifest_unlocked(self, manifest: Dict[str, Any]):
        encrypted_str = encrypt_json(manifest)
        with open(self.manifest_file, "w") as f:
            f.write(encrypted_str)

    def get_media_file_path(self, media_id: str) -> Optional[Tuple[str, str, str]]:
        """
        Returns (abs_file_path, mime_type, original_filename) if media_id belongs to tenant.
        Returns None if not found, invalid, or unauthorized.
        """
        manifest = self.load_manifest()
        item = manifest.get(media_id)
        if not item or "storage_path" not in item:
            return None
        abs_path = os.path.abspath(os.path.join(self.tenant_dir, item["storage_path"]))
        # Enforce strict path traversal verification
        if not abs_path.startswith(os.path.abspath(self.tenant_dir)):
            return None
        if not os.path.exists(abs_path):
            return None
        return abs_path, item.get("mime_type", "image/jpeg"), item.get("original_filename", "photo.jpg")

    def get_media_thumbnail_bytes(self, media_id: str) -> Optional[bytes]:
        """
        Returns the 400x400 square JPEG thumbnail bytes for media_id.
        If thumbnail does not exist on disk, generates it on-the-fly from original media file.
        """
        manifest = self.load_manifest()
        item = manifest.get(media_id)
        if not item or "storage_path" not in item:
            return None

        rel_thumb_path = item.get("thumb_path") or os.path.join("media", f"{media_id}_thumb.dat")
        abs_thumb_path = os.path.abspath(os.path.join(self.tenant_dir, rel_thumb_path))

        if os.path.exists(abs_thumb_path):
            try:
                with open(abs_thumb_path, "rb") as f:
                    return f.read()
            except Exception:
                pass

        # Fallback: Read original file and generate thumbnail on-the-fly
        res = self.get_media_file_path(media_id)
        if not res:
            return None
        abs_orig_path, mime_type, orig_filename = res
        try:
            with open(abs_orig_path, "rb") as f:
                orig_bytes = f.read()
            from backend.thumbnail import generate_square_thumbnail
            is_vid = mime_type.startswith("video") or orig_filename.lower().endswith((".mp4", ".mov", ".avi", ".mkv", ".webm"))
            thumb_bytes = generate_square_thumbnail(orig_bytes, is_video=is_vid)
            if thumb_bytes:
                try:
                    with open(abs_thumb_path, "wb") as tf:
                        tf.write(thumb_bytes)
                except Exception:
                    pass
                return thumb_bytes
        except Exception as e:
            print(f"[Thumbnail Error] On-the-fly thumbnail fallback failed for {media_id}: {e}")
        return None
