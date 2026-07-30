# Handoff Report: Flat Storage Enforcement & Backward Compatibility Analysis

## 1. Observation

Direct code analysis of `brighthorizon-photo-extractor` revealed the following key implementation details across the codebase:

### A. Flat Storage Enforcement & UI Remnants
- **`backend/scraper_engine.py` (Line 62)**:
  ```python
  self.layout_mode = "flat" # Hardcode to flat mode
  ```
  The scraper engine explicitly sets `self.layout_mode` to `"flat"`.
- **`backend/server.py` (Lines 66, 469, 537-539)**:
  ```python
  class ArchiveRequest(BaseModel):
      layout_mode: str = "flat"
  ...
  # Line 469 in start_extraction:
  options = {
      "sync_mode": req.sync_mode,
      "start_date": req.start_date,
      "layout_mode": "flat",
      "child": req.child
  }
  ...
  # Lines 537-539 in create_archive:
  @app.post("/api/archive/create")
  def create_archive(req: ArchiveRequest, tenant: TenantStorage = Depends(get_current_tenant)):
      task = start_zip_task(tenant, req.layout_mode)
      return task
  ```
  While `start_extraction` hardcodes `"layout_mode": "flat"`, the endpoint `/api/archive/create` accepts `ArchiveRequest(layout_mode=...)` from the client and passes `req.layout_mode` to `start_zip_task()`.
- **`frontend/src/components/ArchiveManager.tsx` (Lines 9, 48, 85-114)**:
  ```tsx
  const [layoutMode, setLayoutMode] = useState<string>('flat');
  ...
  // Line 48:
  body: JSON.stringify({ layout_mode: layoutMode })
  ...
  // Lines 85-114:
  <label className="text-xs font-semibold uppercase tracking-wider text-slate-700">Layout Format:</label>
  <div className="grid grid-cols-2 p-1 bg-slate-100 border border-slate-200 rounded-xl text-xs font-medium w-full sm:w-auto">
    <button type="button" onClick={() => setLayoutMode('flat')} ...>Flat</button>
    <button type="button" onClick={() => setLayoutMode('nested')} ...>Nested</button>
  </div>
  ```
  **Finding**: The UI still contains layout selection buttons ("Flat" vs "Nested") and sends `layout_mode` to `/api/archive/create`. Nested layout option has **not** been completely stripped from the UI component or the ZIP archive generator.

### B. Disk Storage Architecture & Manifest Schema
- **`backend/database.py` (Lines 97-123)**:
  ```python
  media_id = str(uuid.uuid4())
  rel_storage_path = os.path.join("media", f"{media_id}.dat")
  abs_storage_path = os.path.abspath(os.path.join(self.tenant_dir, rel_storage_path))
  ...
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
      "storage_path": rel_storage_path
  }
  ```
  Physical files on disk are stored flat under `data/tenants/<tenant_id>/media/<uuid>.dat`.
- **Path Resolution & Traversal Prevention (`backend/database.py` Lines 87-88, 101-102, 134-137)**:
  ```python
  abs_path = os.path.abspath(os.path.join(self.tenant_dir, item["storage_path"]))
  if not abs_path.startswith(os.path.abspath(self.tenant_dir)):
      return None
  ```
  `TenantStorage` enforces strict prefix validation to ensure files stay within `tenant_dir`.

### C. ZIP Archive Generation (`backend/archive_stream.py`)
- **`backend/archive_stream.py` (Lines 56-73)**:
  ```python
  for media_id, item in manifest.items():
      rel_path = item["storage_path"]
      abs_src = os.path.join(tenant_storage.tenant_dir, rel_path)
      
      if os.path.exists(abs_src):
          child = item.get("child", "Child")
          orig_name = item.get("original_filename", f"{media_id}.jpg")
          date_str = item.get("date", "")
          year = item.get("year", "")
          month = item.get("month", "")
          
          if layout == "nested" and year and month:
              arcname = os.path.join(child, f"{year:04d}", f"{month:02d}", orig_name)
          else:
              arcname = os.path.join(child, orig_name)
              
          zf.write(abs_src, arcname=arcname)
  ```
  **Finding 1 (Omission of Path Traversal Check in ZIP stream)**: Unlike `database.py`, `archive_stream.py` line 58 constructs `abs_src = os.path.join(tenant_storage.tenant_dir, rel_path)` without verifying `abs_src.startswith(tenant_storage.tenant_dir)`.
  **Finding 2 (ZIP Internal Path Traversal)**: `arcname` is created using `os.path.join(child, orig_name)`. If `child` or `orig_name` stored in `manifest.json` contains `../` or absolute path prefixes, `zf.write()` will include those relative traversal paths inside the ZIP payload.
  **Finding 3 (Filename Collision Handling)**: In flat mode, `arcname` is `os.path.join(child, orig_name)`. If multiple manifest entries share the same `child` and `original_filename` (e.g., legacy entries or identical post dates without unique hex suffixes), `archive_stream.py` writes duplicate filenames into the ZIP without collision detection or deduplication indexing.

---

## 2. Logic Chain

1. **Flat Storage Enforcement Assessment**:
   - The backend storage architecture (`TenantStorage`) natively uses flat storage (`media/<uuid>.dat`) regardless of requested layout.
   - The extraction process (`scraper_engine.py`) hardcodes `self.layout_mode = "flat"`.
   - **Gap**: `frontend/src/components/ArchiveManager.tsx` retains UI controls for selecting between "Flat" and "Nested" ZIP archive creation. `backend/server.py` passes `req.layout_mode` to `start_zip_task()`, which supports both `nested` (`child/YYYY/MM/filename`) and `flat` (`child/filename`) inside the generated ZIP file. Therefore, flat mode is enforced for *on-disk media storage*, but nested structure is still supported and exposed in the UI for *ZIP archive creation*.

2. **Backward Compatibility Assessment**:
   - `manifest.json` (`manifest.enc`) uses UUID-based relative paths (`storage_path: "media/<uuid>.dat"`).
   - Because `storage_path` decouples physical storage from display properties (`original_filename`, `child`, `date`), defaulting to flat storage on disk maintains 100% backward compatibility with pre-existing `manifest.json` entries.
   - Direct file streaming (`/api/media/{media_id}`) resolves files using `storage_path` via `TenantStorage.get_media_file_path()`, unaffected by layout settings.

3. **ZIP Stream & Security Analysis**:
   - **Path Traversal**: `database.py` validates `abs_path.startswith(tenant_dir)`. However, `archive_stream.py` reads `storage_path`, `child`, and `original_filename` directly from the manifest without sanitizing `arcname`. If a modified or malicious manifest entry contains `child: "../"` or `original_filename: "../../etc/passwd"`, `zf.write()` will write dangerous entry names inside the ZIP archive.
   - **Filename Collisions**: In flat mode, ZIP archive paths are structured as `child/original_filename`. Current scraper logic generates filenames as `f"{child_name} {date_str} ({obj_id[:6]}).{ext}"`, which avoids collisions by including `obj_id[:6]`. However, if legacy manifest records lack `obj_id` in `original_filename`, multiple files for the same child on the same date will collide, causing duplicate filenames within the ZIP container.

---

## 3. Caveats

- **Scope Limit**: This investigation was strictly read-only; no code modifications were applied to backend or frontend files.
- **Standalone CLI vs Server**: Standalone CLI scripts (`main.py` if present in root or docs) or legacy scripts were replaced by `scraper_engine.py` in the server architecture.
- **Environment**: Tested inspection against backend Python files (`server.py`, `scraper_engine.py`, `database.py`, `archive_stream.py`) and React frontend (`ArchiveManager.tsx`).

---

## 4. Conclusion

1. **Flat Storage Enforcement**:
   - Enforced for physical media files stored on disk (`media/<uuid>.dat`).
   - **Not strictly enforced for ZIP exports**: `ArchiveManager.tsx` UI and `archive_stream.py` backend still support nested folder hierarchy within generated ZIP archives (`child/YYYY/MM/filename`). If total flat enforcement is required, the UI toggle in `ArchiveManager.tsx` should be removed/deprecated and `archive_stream.py` forced to flat mode.

2. **Backward Compatibility**:
   - Fully preserved. Decoupling `storage_path` (`media/<uuid>.dat`) from `original_filename` allows seamless retrieval of legacy media records.

3. **ZIP Stream Security & Safety**:
   - **Path Traversal Risk**: Missing `arcname` path sanitization in `archive_stream.py` allows potential Zip Slip / path traversal in archives if manifest metadata is untrusted.
   - **Filename Collision Risk**: No collision detection logic exists in `archive_stream.py` when building `arcname` in flat mode.

---

## 5. Verification Method

To verify these findings:

1. **UI Inspection**:
   Inspect `frontend/src/components/ArchiveManager.tsx` lines 85-114 to confirm the presence of the "Flat" and "Nested" layout format toggle buttons.

2. **Backend ZIP Stream Verification**:
   Inspect `backend/archive_stream.py` lines 67-71 to verify that `layout == "nested"` is still processed to generate nested ZIP paths (`os.path.join(child, f"{year:04d}", f"{month:02d}", orig_name)`).

3. **Path Traversal Check**:
   Inspect `backend/archive_stream.py` line 72 (`zf.write(abs_src, arcname=arcname)`). Note the absence of `os.path.basename` or `arcname` sanitization prior to ZIP writing.
