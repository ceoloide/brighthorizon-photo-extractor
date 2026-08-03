# SPDX-License-Identifier: MIT
"""
Unit Test Suite for backend/pipeline.py.
Tests PNG tEXt injection, JPEG EXIF/COM injection, Eastern Time utime setting,
and Playwright extraction pipeline flow.
"""

import os
import zlib
import struct
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock, patch

from pathlib import Path

import pytest
import piexif

from backend import security_isolation
from backend.pipeline import (
    inject_png_text_chunk,
    inject_jpeg_exif,
    _inject_jpeg_com_fallback,
    set_eastern_utime,
    run_extraction_pipeline,
)


# Helper fixtures to generate minimal valid image bytes
def create_minimal_png_bytes() -> bytes:
    png_magic = b"\x89PNG\r\n\x1a\n"
    ihdr_data = b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    ihdr_crc = struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_data) & 0xffffffff)
    ihdr_chunk = struct.pack(">I", 13) + b"IHDR" + ihdr_data + ihdr_crc

    iend_crc = struct.pack(">I", zlib.crc32(b"IEND") & 0xffffffff)
    iend_chunk = struct.pack(">I", 0) + b"IEND" + iend_crc

    return png_magic + ihdr_chunk + iend_chunk


def create_minimal_jpeg_bytes() -> bytes:
    return (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00\x60\x00\x60\x00\x00"
        b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\x09\x09\x08\x0a"
        b"\x0c\x14\x0d\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a"
        b"\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xff\xc0\x00\x0b\x08\x00"
        b"\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01"
        b"\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07"
        b"\x08\x09\x0a\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\x7f\x00\xff\xd9"
    )


# =============================================================================
# Category 1: Pure-Python PNG Metadata Chunk Injection Tests
# =============================================================================

def test_inject_png_text_chunk_valid(tmp_path):
    png_file = tmp_path / "test.png"
    png_file.write_bytes(create_minimal_png_bytes())

    comment = "Bright Horizons test comment for Byron"
    inject_png_text_chunk(str(png_file), comment)

    data = png_file.read_bytes()

    # Header check (8B)
    assert data.startswith(b"\x89PNG\r\n\x1a\n")

    # Verify insertion at offset 33 (after 8B header + 25B IHDR)
    chunk_len = struct.unpack(">I", data[33:37])[0]
    chunk_type = data[37:41]
    payload = data[41:41+chunk_len]
    crc_actual = struct.unpack(">I", data[41+chunk_len:45+chunk_len])[0]

    assert chunk_type == b"tEXt"
    assert payload == b"Description\x00" + comment.encode("utf-8")

    crc_expected = zlib.crc32(chunk_type + payload) & 0xffffffff
    assert crc_actual == crc_expected


def test_inject_png_text_chunk_duplicate(tmp_path):
    png_file = tmp_path / "test_dup.png"
    png_file.write_bytes(create_minimal_png_bytes())

    inject_png_text_chunk(str(png_file), "Initial comment")
    inject_png_text_chunk(str(png_file), "Updated comment")

    data = png_file.read_bytes()

    # Ensure only ONE Description tEXt chunk exists and contains updated comment
    assert data.count(b"tEXt") == 1
    assert data.count(b"Description") == 1
    assert b"Updated comment" in data
    assert b"Initial comment" not in data


def test_inject_png_invalid_header(tmp_path):
    bad_file = tmp_path / "bad.png"
    bad_file.write_bytes(b"NOT A PNG FILE")

    with pytest.raises(ValueError, match="Invalid PNG file header"):
        inject_png_text_chunk(str(bad_file), "Test comment")


# =============================================================================
# Category 2: JPEG EXIF & COM Fallback Tests
# =============================================================================

def test_inject_jpeg_exif_piexif(tmp_path):
    jpeg_file = tmp_path / "test.jpg"
    jpeg_file.write_bytes(create_minimal_jpeg_bytes())

    comment = "Bright Horizons JPEG EXIF comment"
    inject_jpeg_exif(str(jpeg_file), comment)

    exif_dict = piexif.load(str(jpeg_file))
    assert exif_dict["0th"][piexif.ImageIFD.ImageDescription] == comment.encode("utf-8")
    assert exif_dict["Exif"][piexif.ExifIFD.UserComment] == b"ASCII\x00\x00\x00" + comment.encode("utf-8")


def test_inject_jpeg_exif_fallback(tmp_path):
    jpeg_file = tmp_path / "test_fallback.jpg"
    jpeg_file.write_bytes(b"\xff\xd8\xff\xd9")  # Minimal JPEG SOI/EOI without EXIF

    comment = "Fallback COM marker comment"
    # Force piexif.dump to fail so fallback path executes
    with patch("piexif.dump", side_effect=RuntimeError("EXIF dump failed")):
        inject_jpeg_exif(str(jpeg_file), comment)

    data = jpeg_file.read_bytes()
    assert data.startswith(b"\xff\xd8")
    assert data[2:4] == b"\xff\xfe"  # COM marker
    assert comment.encode("utf-8") in data


def test_inject_jpeg_invalid_header(tmp_path):
    bad_file = tmp_path / "bad.jpg"
    bad_file.write_bytes(b"NOT A JPEG FILE")

    with pytest.raises(ValueError, match="Invalid JPEG file header"):
        _inject_jpeg_com_fallback(str(bad_file), "Comment")


# =============================================================================
# Category 3: Eastern Time utime Setting Tests
# =============================================================================

def test_set_eastern_utime_est(tmp_path):
    test_file = tmp_path / "winter.txt"
    test_file.write_text("winter")

    # Jan 15 2026 (EST, UTC-5) -> 10:00:00 AM EST = 15:00:00 UTC
    epoch = set_eastern_utime(str(test_file), "2026-01-15")

    expected_dt = datetime(2026, 1, 15, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
    assert epoch == expected_dt.timestamp()
    assert epoch == 1768489200.0

    stat_mtime = os.stat(str(test_file)).st_mtime
    assert stat_mtime == 1768489200.0


def test_set_eastern_utime_edt(tmp_path):
    test_file = tmp_path / "summer.txt"
    test_file.write_text("summer")

    # Jul 15 2026 (EDT, UTC-4) -> 10:00:00 AM EDT = 14:00:00 UTC
    epoch = set_eastern_utime(str(test_file), "2026-07-15")

    expected_dt = datetime(2026, 7, 15, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
    assert epoch == expected_dt.timestamp()
    assert epoch == 1784124000.0

    stat_mtime = os.stat(str(test_file)).st_mtime
    assert stat_mtime == 1784124000.0


def test_set_eastern_utime_datetime_input(tmp_path):
    test_file = tmp_path / "dt.txt"
    test_file.write_text("datetime")

    dt_obj = datetime(2026, 5, 20, 14, 30, 0)
    epoch = set_eastern_utime(str(test_file), dt_obj)

    expected_dt = datetime(2026, 5, 20, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
    assert epoch == expected_dt.timestamp()


# =============================================================================
# Category 4: Extraction Pipeline Execution Tests (Mocked Browser)
# =============================================================================

def test_run_extraction_pipeline_full_sync(tmp_path):
    mock_page = MagicMock()
    mock_page.url = "https://mybrightday.brighthorizons.com/dashboard/parents.html?dependent_id=dep123"

    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.body.return_value = create_minimal_png_bytes()
    mock_page.request.get.return_value = mock_response

    output_dir = str(tmp_path / "downloads")

    with patch("backend.dom_parser.parse_timeframe_links") as mock_parse_tf, \
         patch("backend.dom_parser.extract_feed_items") as mock_extract_items, \
         patch("backend.dom_parser.click_timeframe_tile") as mock_click_tf, \
         patch("backend.dom_parser.dismiss_cdk_overlays"):

        mock_parse_tf.return_value = [{"text": "jun 2026", "year": 2026, "locator": MagicMock()}]
        mock_extract_items.return_value = [{
            "obj_id": "photo999",
            "date_str": "2026-06-15",
            "is_video": False,
            "download_url": "https://mybrightday.brighthorizons.com/remote/v1/obj_attachment?obj=photo999",
            "comment": "Byron drawing a picture"
        }]

        logs = []
        result = run_extraction_pipeline(
            page=mock_page,
            child_name="Byron",
            dependent_id="dep123",
            output_dir=output_dir,
            sync_mode="full",
            logger=logs.append
        )

        assert result["status"] == "completed"
        assert result["downloaded_count"] == 1
        assert "photo999" in result["manifest"]

        # Check saved file
        expected_file = Path(security_isolation.resolve_child_output_path(output_dir, "Byron", "2026-06-15_photo999.png"))
        assert expected_file.exists()
        saved_bytes = expected_file.read_bytes()
        assert b"Description\x00Bright Horizons photo for Byron on 2026-06-15: Byron drawing a picture" in saved_bytes

        # Verify utime modification
        stat_mtime = os.stat(str(expected_file)).st_mtime
        assert stat_mtime == 1781532000.0  # 2026-06-15 10:00 AM EDT


def test_run_extraction_pipeline_incremental(tmp_path):
    mock_page = MagicMock()
    mock_page.url = "https://mybrightday.brighthorizons.com/dashboard/parents.html?dependent_id=dep123"

    output_dir = str(tmp_path / "downloads")
    manifest_cache = {"photo999": {"obj_id": "photo999", "child": "Byron"}}

    with patch("backend.dom_parser.parse_timeframe_links") as mock_parse_tf, \
         patch("backend.dom_parser.extract_feed_items") as mock_extract_items, \
         patch("backend.dom_parser.click_timeframe_tile"), \
         patch("backend.dom_parser.dismiss_cdk_overlays"):

        mock_parse_tf.return_value = [{"text": "jun 2026", "year": 2026, "locator": MagicMock()}]
        mock_extract_items.return_value = [{
            "obj_id": "photo999",
            "date_str": "2026-06-15",
            "is_video": False,
            "download_url": "https://mybrightday.brighthorizons.com/remote/v1/obj_attachment?obj=photo999",
            "comment": "Byron drawing"
        }]

        logs = []
        result = run_extraction_pipeline(
            page=mock_page,
            child_name="Byron",
            dependent_id="dep123",
            output_dir=output_dir,
            sync_mode="incremental",
            manifest_cache=manifest_cache,
            logger=logs.append
        )

        assert result["status"] == "completed"
        assert result["downloaded_count"] == 0
        assert any("Halting feed scan" in m for m in logs)


def test_run_extraction_pipeline_start_date(tmp_path):
    mock_page = MagicMock()
    mock_page.url = "https://mybrightday.brighthorizons.com/dashboard/parents.html?dependent_id=dep123"

    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.body.return_value = create_minimal_png_bytes()
    mock_page.request.get.return_value = mock_response

    output_dir = str(tmp_path / "downloads")

    with patch("backend.dom_parser.parse_timeframe_links") as mock_parse_tf, \
         patch("backend.dom_parser.extract_feed_items") as mock_extract_items, \
         patch("backend.dom_parser.click_timeframe_tile"), \
         patch("backend.dom_parser.dismiss_cdk_overlays"):

        mock_parse_tf.return_value = [{"text": "may 2026", "year": 2026, "locator": MagicMock()}]
        mock_extract_items.return_value = [{
            "obj_id": "old_photo",
            "date_str": "2026-05-10",
            "is_video": False,
            "download_url": "https://mybrightday.brighthorizons.com/remote/v1/obj_attachment?obj=old_photo",
            "comment": "Old photo"
        }]

        logs = []
        result = run_extraction_pipeline(
            page=mock_page,
            child_name="Byron",
            dependent_id="dep123",
            output_dir=output_dir,
            start_date="2026-06-01",
            sync_mode="full",
            logger=logs.append
        )

        assert result["status"] == "completed"
        assert result["downloaded_count"] == 0
        assert result["skipped_count"] == 1


def test_run_extraction_pipeline_unauthenticated():
    mock_page = MagicMock()
    mock_page.url = "https://sso.brighthorizons.com/login"

    with pytest.raises(RuntimeError, match="Unauthenticated session"):
        run_extraction_pipeline(
            page=mock_page,
            child_name="Byron",
            dependent_id="dep123",
            output_dir="/tmp",
        )


def test_run_extraction_pipeline_cancellation(tmp_path):
    mock_page = MagicMock()
    mock_page.url = "https://mybrightday.brighthorizons.com/dashboard/parents.html?dependent_id=dep123"

    output_dir = str(tmp_path / "downloads")

    with patch("backend.dom_parser.parse_timeframe_links") as mock_parse_tf, \
         patch("backend.dom_parser.dismiss_cdk_overlays"):

        mock_parse_tf.return_value = [{"text": "jun 2026", "year": 2026, "locator": MagicMock()}]

        result = run_extraction_pipeline(
            page=mock_page,
            child_name="Byron",
            dependent_id="dep123",
            output_dir=output_dir,
            cancel_checker=lambda: True
        )

        assert result["status"] == "cancelled"
        assert result["downloaded_count"] == 0
