import os
import io
import json
import pytest
from unittest.mock import MagicMock, patch
from PIL import Image

from backend.scraper_engine import check_and_refetch_if_200x200, ScraperJob
from backend.database import TenantStorage

def create_dummy_image_bytes(width: int, height: int, fmt: str = "JPEG") -> bytes:
    img = Image.new("RGB", (width, height), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()

def test_check_and_refetch_non_200_image():
    """Higher resolution image should pass through without refetching."""
    data_bytes = create_dummy_image_bytes(800, 600)
    out_bytes, upgraded = check_and_refetch_if_200x200(
        file_bytes=data_bytes,
        o_id="test_obj",
        k_id="test_key",
        req_headers={},
        session_cookies={},
        is_vid=False
    )
    assert upgraded is False
    assert out_bytes == data_bytes

def test_check_and_refetch_video():
    """Valid video payload should pass through without refetching."""
    data_bytes = b"ftypisom_valid_mp4_bytes"
    out_bytes, upgraded = check_and_refetch_if_200x200(
        file_bytes=data_bytes,
        o_id="test_obj",
        k_id="test_key",
        req_headers={},
        session_cookies={},
        is_vid=True
    )
    assert upgraded is False
    assert out_bytes == data_bytes

@patch("requests.get")
def test_check_and_refetch_video_jpeg_fallback(mock_get):
    """Video payload returning JPEG image should trigger signed URL refetch and return MP4 bytes if upgraded."""
    jpeg_bytes = create_dummy_image_bytes(200, 200)
    video_bytes = b"ftypisom_real_video_payload"

    mock_resp_json = MagicMock()
    mock_resp_json.status_code = 200
    mock_resp_json.content = json.dumps({"signed_url": "https://storage.googleapis.com/video.mp4"}).encode("utf-8")

    mock_resp_gcs = MagicMock()
    mock_resp_gcs.status_code = 200
    mock_resp_gcs.content = video_bytes

    mock_get.side_effect = [mock_resp_json, mock_resp_gcs]

    logs = []
    out_bytes, upgraded = check_and_refetch_if_200x200(
        file_bytes=jpeg_bytes,
        o_id="vid_123",
        k_id="key_123",
        req_headers={"User-Agent": "Test"},
        session_cookies={},
        is_vid=True,
        max_retries=2,
        log_func=logs.append
    )

    assert upgraded is True
    assert out_bytes == video_bytes
    assert any("Video Stream Upgrade Success" in l for l in logs)

@patch("requests.get")
def test_check_and_refetch_200x200_upgrade_success(mock_get):
    """200x200 image should trigger signed URL refetch and return upgraded payload if high-res."""
    thumb_bytes = create_dummy_image_bytes(200, 200)
    highres_bytes = create_dummy_image_bytes(1280, 720)

    mock_resp_json = MagicMock()
    mock_resp_json.status_code = 200
    mock_resp_json.content = json.dumps({"signed_url": "https://storage.googleapis.com/highres.jpg"}).encode("utf-8")

    mock_resp_gcs = MagicMock()
    mock_resp_gcs.status_code = 200
    mock_resp_gcs.content = highres_bytes

    mock_get.side_effect = [mock_resp_json, mock_resp_gcs]

    logs = []
    out_bytes, upgraded = check_and_refetch_if_200x200(
        file_bytes=thumb_bytes,
        o_id="obj_123",
        k_id="key_123",
        req_headers={"User-Agent": "Test"},
        session_cookies={},
        is_vid=False,
        max_retries=2,
        log_func=logs.append
    )

    assert upgraded is True
    assert out_bytes == highres_bytes
    assert any("Resolution Upgrade Success" in l for l in logs)

@patch("requests.get")
def test_check_and_refetch_200x200_remains_200(mock_get):
    """If retries still return 200x200, original asset is retained."""
    thumb_bytes = create_dummy_image_bytes(200, 200)

    mock_resp_json = MagicMock()
    mock_resp_json.status_code = 200
    mock_resp_json.content = json.dumps({"signed_url": "https://storage.googleapis.com/thumb.jpg"}).encode("utf-8")

    mock_resp_gcs = MagicMock()
    mock_resp_gcs.status_code = 200
    mock_resp_gcs.content = thumb_bytes

    mock_get.side_effect = [mock_resp_json, mock_resp_gcs, mock_resp_json, mock_resp_gcs]

    logs = []
    out_bytes, upgraded = check_and_refetch_if_200x200(
        file_bytes=thumb_bytes,
        o_id="obj_123",
        k_id="key_123",
        req_headers={"User-Agent": "Test"},
        session_cookies={},
        is_vid=False,
        max_retries=2,
        log_func=logs.append
    )

    assert upgraded is False
    assert out_bytes == thumb_bytes
    assert any("Remediation Notice" in l or "remains" in l for l in logs)

@patch("backend.scraper_engine.check_and_refetch_if_200x200")
def test_post_extraction_thumbnail_sweep(mock_refetch, tmp_path):
    """Post-extraction job sweep identifies 200x200 thumbnails in manifest and executes 1-time refetch pass."""
    storage = TenantStorage(email="sweep_user@example.com")
    storage.tenant_dir = str(tmp_path)
    storage.media_dir = os.path.join(storage.tenant_dir, "media")
    storage.archives_dir = os.path.join(storage.tenant_dir, "archives")
    storage.user_data_dir = os.path.join(storage.tenant_dir, "user_data")
    storage.logs_dir = os.path.join(storage.tenant_dir, "logs")
    storage._ensure_dirs()

    thumb_bytes = create_dummy_image_bytes(200, 200)
    highres_bytes = create_dummy_image_bytes(1024, 768)

    entry = storage.add_media_entry(
        obj_id="obj_sweep_1",
        child="Byron",
        date_str="2026-06-01",
        original_filename="Byron 2026-06-01 (01).jpg",
        comment="Test Sweep",
        file_bytes=thumb_bytes,
        mime_type="image/jpeg"
    )

    mock_refetch.return_value = (highres_bytes, True)

    job = ScraperJob(tenant_storage=storage, password="pwd", options={})

    job._run_post_extraction_thumbnail_sweep()

    mock_refetch.assert_called_once()
    assert mock_refetch.call_args[1]["max_retries"] == 1

    # Verify storage entry was upgraded to high-res bytes
    updated_path = os.path.join(storage.tenant_dir, entry["storage_path"])
    with open(updated_path, "rb") as f:
        data = f.read()

    with Image.open(io.BytesIO(data)) as img:
        assert img.width == 1024
        assert img.height == 768
