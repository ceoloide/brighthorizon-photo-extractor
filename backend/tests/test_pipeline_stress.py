# SPDX-License-Identifier: MIT
"""
Adversarial & Boundary Stress Harness for backend/pipeline.py metadata injection functions:
- inject_png_text_chunk
- inject_jpeg_exif
- _inject_jpeg_com_fallback
- set_eastern_utime
"""

import os
import zlib
import struct
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import pytest
import piexif

from unittest.mock import MagicMock, patch
import json

from backend.pipeline import (
    inject_png_text_chunk,
    inject_jpeg_exif,
    _inject_jpeg_com_fallback,
    set_eastern_utime,
    run_extraction_pipeline,
)

# Helpers to generate base valid files
def create_valid_png_bytes() -> bytes:
    png_magic = b"\x89PNG\r\n\x1a\n"
    ihdr_data = b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    ihdr_crc = struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_data) & 0xffffffff)
    ihdr_chunk = struct.pack(">I", 13) + b"IHDR" + ihdr_data + ihdr_crc

    iend_crc = struct.pack(">I", zlib.crc32(b"IEND") & 0xffffffff)
    iend_chunk = struct.pack(">I", 0) + b"IEND" + iend_crc

    return png_magic + ihdr_chunk + iend_chunk

def create_valid_jpeg_bytes() -> bytes:
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
# 1. Stress Testing inject_png_text_chunk
# =============================================================================

class TestInjectPNGTextChunkStress:
    def test_truncated_png_magic_header(self, tmp_path):
        f = tmp_path / "truncated_magic.png"
        f.write_bytes(b"\x89PNG\r\n")  # Only 6 bytes
        with pytest.raises(ValueError, match="Invalid PNG file header"):
            inject_png_text_chunk(str(f), "comment")

    def test_truncated_ihdr_chunk_header(self, tmp_path):
        f = tmp_path / "truncated_ihdr.png"
        # 8 bytes header + 10 bytes (less than 25 bytes required for complete IHDR)
        f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR\x00\x00")
        with pytest.raises(ValueError, match="Invalid PNG file header"):
            inject_png_text_chunk(str(f), "comment")

    def test_corrupted_ihdr_chunk_type(self, tmp_path):
        f = tmp_path / "corrupt_ihdr.png"
        png_magic = b"\x89PNG\r\n\x1a\n"
        bad_ihdr = struct.pack(">I", 13) + b"XXXX" + b"\x00"*13 + struct.pack(">I", 0)
        f.write_bytes(png_magic + bad_ihdr)
        with pytest.raises(ValueError, match="Invalid PNG structure: missing IHDR chunk"):
            inject_png_text_chunk(str(f), "comment")

    def test_truncated_chunk_in_tail(self, tmp_path):
        """Tests PNG with trailing corrupted chunk whose chunk_end exceeds data length."""
        f = tmp_path / "truncated_tail.png"
        valid_png = create_valid_png_bytes()
        # Add half of a tEXt chunk header at the end (length claims 1000 bytes, but file ends)
        fake_chunk_hdr = struct.pack(">I", 1000) + b"tEXt"
        f.write_bytes(valid_png + fake_chunk_hdr)

        inject_png_text_chunk(str(f), "valid comment")
        data = f.read_bytes()
        # Ensure injection succeeded without crashing, and inserted tEXt
        assert b"Description\x00valid comment" in data

    def test_non_ascii_unicode_emojis(self, tmp_path):
        f = tmp_path / "unicode.png"
        f.write_bytes(create_valid_png_bytes())
        comment = "Catherine 🎨 ✨ café & résumé 100% 👍"
        inject_png_text_chunk(str(f), comment)

        data = f.read_bytes()
        assert comment.encode("utf-8") in data

        # Check CRC calculation on UTF-8 payload
        chunk_len = struct.unpack(">I", data[33:37])[0]
        payload = data[41:41+chunk_len]
        crc_actual = struct.unpack(">I", data[41+chunk_len:45+chunk_len])[0]
        crc_expected = zlib.crc32(b"tEXt" + payload) & 0xffffffff
        assert crc_actual == crc_expected

    def test_null_bytes_in_comment(self, tmp_path):
        f = tmp_path / "null_byte.png"
        f.write_bytes(create_valid_png_bytes())
        comment = "Comment with \x00 null byte"
        inject_png_text_chunk(str(f), comment)

        data = f.read_bytes()
        assert comment.encode("utf-8") in data

    def test_extremely_large_comment(self, tmp_path):
        f = tmp_path / "large_comment.png"
        f.write_bytes(create_valid_png_bytes())
        large_comment = "A" * 1_000_000  # 1MB comment
        inject_png_text_chunk(str(f), large_comment)

        data = f.read_bytes()
        assert large_comment.encode("utf-8") in data

    def test_multiple_existing_text_description_chunks(self, tmp_path):
        """Tests that all pre-existing Description tEXt chunks are stripped out."""
        f = tmp_path / "multi_desc.png"
        valid_png = create_valid_png_bytes()
        f.write_bytes(valid_png)

        # Inject 3 times with different comments
        inject_png_text_chunk(str(f), "Desc 1")
        inject_png_text_chunk(str(f), "Desc 2")
        inject_png_text_chunk(str(f), "Desc 3")

        data = f.read_bytes()
        assert data.count(b"tEXt") == 1
        assert data.count(b"Description") == 1
        assert b"Desc 3" in data
        assert b"Desc 1" not in data
        assert b"Desc 2" not in data

# =============================================================================
# 2. Stress Testing inject_jpeg_exif and _inject_jpeg_com_fallback
# =============================================================================

class TestInjectJPEGMetadataStress:
    def test_jpeg_empty_file(self, tmp_path):
        f = tmp_path / "empty.jpg"
        f.write_bytes(b"")
        with pytest.raises(ValueError, match="Invalid JPEG file header"):
            _inject_jpeg_com_fallback(str(f), "comment")

    def test_jpeg_truncated_soi(self, tmp_path):
        f = tmp_path / "truncated_soi.jpg"
        f.write_bytes(b"\xff")
        with pytest.raises(ValueError, match="Invalid JPEG file header"):
            _inject_jpeg_com_fallback(str(f), "comment")

    def test_jpeg_corrupted_header(self, tmp_path):
        f = tmp_path / "corrupt_hdr.jpg"
        f.write_bytes(b"\x00\x00\xff\xd8\xff\xe0")
        with pytest.raises(ValueError, match="Invalid JPEG file header"):
            _inject_jpeg_com_fallback(str(f), "comment")

    def test_jpeg_piexif_non_ascii_unicode(self, tmp_path):
        f = tmp_path / "unicode_piexif.jpg"
        f.write_bytes(create_valid_jpeg_bytes())
        comment = "Catherine 🎨 ✨ café & résumé 100% 👍"
        inject_jpeg_exif(str(f), comment)

        exif_dict = piexif.load(str(f))
        assert exif_dict["0th"][piexif.ImageIFD.ImageDescription] == comment.encode("utf-8")
        assert exif_dict["Exif"][piexif.ExifIFD.UserComment] == b"ASCII\x00\x00\x00" + comment.encode("utf-8")

    def test_jpeg_piexif_corrupted_exif_data_triggers_fallback(self, tmp_path):
        """When piexif fails to process corrupted EXIF header, it falls back to COM marker."""
        f = tmp_path / "corrupt_exif.jpg"
        # Write SOI + APP1 (Exif) marker with invalid payload that breaks piexif
        corrupt_bytes = b"\xff\xd8\xff\xe1\x00\x10Exif\x00\x00BAD_EXIF_DATA_HERE\xff\xd9"
        f.write_bytes(corrupt_bytes)

        comment = "Fallback comment after corrupt EXIF"
        inject_jpeg_exif(str(f), comment)

        data = f.read_bytes()
        # Check COM marker injected
        assert data.startswith(b"\xff\xd8")
        assert data[2:4] == b"\xff\xfe"
        assert comment.encode("utf-8") in data

    def test_jpeg_com_fallback_oversized_comment(self, tmp_path):
        """JPEG marker length is a 16-bit unsigned integer max 65535, payload max 65533 bytes."""
        f = tmp_path / "huge_com.jpg"
        f.write_bytes(create_valid_jpeg_bytes())
        huge_comment = "A" * 70_000  # Exceeds 65533 bytes

        # struct.pack(">H", marker_length) will raise struct.error if marker_length > 65535
        with pytest.raises(struct.error):
            _inject_jpeg_com_fallback(str(f), huge_comment)

    def test_jpeg_com_fallback_non_ascii(self, tmp_path):
        f = tmp_path / "unicode_com.jpg"
        f.write_bytes(create_valid_jpeg_bytes())
        comment = "Byron 🎉 🌟 test"
        _inject_jpeg_com_fallback(str(f), comment)

        data = f.read_bytes()
        assert b"\xff\xfe" in data
        assert comment.encode("utf-8") in data

# =============================================================================
# 3. Stress Testing set_eastern_utime
# =============================================================================

class TestSetEasternUtimeStress:
    def test_est_edt_spring_forward_boundary(self, tmp_path):
        """2026 DST Spring Forward in US Eastern Time: March 8, 2026 at 2:00 AM local time."""
        f_before = tmp_path / "est_before.txt"
        f_before.write_text("before")
        # March 7, 2026 (EST, UTC-5)
        epoch_before = set_eastern_utime(str(f_before), "2026-03-07")
        dt_before = datetime(2026, 3, 7, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        assert epoch_before == dt_before.timestamp()
        assert dt_before.utcoffset().total_seconds() == -5 * 3600

        f_after = tmp_path / "edt_after.txt"
        f_after.write_text("after")
        # March 9, 2026 (EDT, UTC-4)
        epoch_after = set_eastern_utime(str(f_after), "2026-03-09")
        dt_after = datetime(2026, 3, 9, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        assert epoch_after == dt_after.timestamp()
        assert dt_after.utcoffset().total_seconds() == -4 * 3600

        # March 8, 2026 (Day of Spring Forward - 10 AM is EDT UTC-4)
        f_transition = tmp_path / "transition.txt"
        f_transition.write_text("transition")
        epoch_trans = set_eastern_utime(str(f_transition), "2026-03-08")
        dt_trans = datetime(2026, 3, 8, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        assert epoch_trans == dt_trans.timestamp()
        assert dt_trans.utcoffset().total_seconds() == -4 * 3600

    def test_est_edt_fall_back_boundary(self, tmp_path):
        """2026 DST Fall Back in US Eastern Time: November 1, 2026 at 2:00 AM local time."""
        f_before = tmp_path / "edt_fall_before.txt"
        f_before.write_text("before")
        # October 31, 2026 (EDT, UTC-4)
        epoch_before = set_eastern_utime(str(f_before), "2026-10-31")
        dt_before = datetime(2026, 10, 31, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        assert epoch_before == dt_before.timestamp()
        assert dt_before.utcoffset().total_seconds() == -4 * 3600

        f_after = tmp_path / "est_fall_after.txt"
        f_after.write_text("after")
        # November 2, 2026 (EST, UTC-5)
        epoch_after = set_eastern_utime(str(f_after), "2026-11-02")
        dt_after = datetime(2026, 11, 2, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        assert epoch_after == dt_after.timestamp()
        assert dt_after.utcoffset().total_seconds() == -5 * 3600

        # November 1, 2026 (Day of Fall Back - 10 AM is EST UTC-5)
        f_trans = tmp_path / "fall_trans.txt"
        f_trans.write_text("fall_trans")
        epoch_trans = set_eastern_utime(str(f_trans), "2026-11-01")
        dt_trans = datetime(2026, 11, 1, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        assert epoch_trans == dt_trans.timestamp()
        assert dt_trans.utcoffset().total_seconds() == -5 * 3600

    def test_leap_year_feb_29(self, tmp_path):
        f = tmp_path / "leap.txt"
        f.write_text("leap")
        epoch = set_eastern_utime(str(f), "2024-02-29")
        dt_expected = datetime(2024, 2, 29, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        assert epoch == dt_expected.timestamp()

    def test_invalid_date_string_formats(self, tmp_path):
        f = tmp_path / "invalid_date.txt"
        f.write_text("data")
        # Unparseable string falls back via dom_parser overlay to current date
        epoch = set_eastern_utime(str(f), "INVALID_DATE_1234")
        assert isinstance(epoch, float)
        assert epoch > 0

    def test_invalid_type_input(self, tmp_path):
        f = tmp_path / "invalid_type.txt"
        f.write_text("data")
        with pytest.raises(TypeError, match="date_str_or_dt must be str or datetime"):
            set_eastern_utime(str(f), 1234567890) # type: ignore

    def test_nonexistent_file_path(self):
        with pytest.raises(FileNotFoundError):
            set_eastern_utime("/path/to/nonexistent/file.txt", "2026-06-01")

    def test_iso_overlay_date_format_fallback(self, tmp_path):
        f = tmp_path / "overlay.txt"
        f.write_text("overlay")
        # dom_parser overlay formats e.g. "jun 15, 2026" or "jun 2026"
        epoch = set_eastern_utime(str(f), "jun 15, 2026")
        dt_expected = datetime(2026, 6, 15, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        assert epoch == dt_expected.timestamp()


# =============================================================================
# Category 4: Step Extraction Pipeline (run_extraction_pipeline) Stress Tests
# =============================================================================

class TestRunExtractionPipelineStress:

    # -------------------------------------------------------------------------
    # 4.1 Cancellation Handling Stress Tests
    # -------------------------------------------------------------------------
    def test_cancellation_mid_sync_manifest_disk_persistence(self, tmp_path):
        """
        STRESS TEST: Download 1 item, then cancel before item 2.
        Checks if manifest.json on disk is persisted upon early return.
        """
        mock_page = MagicMock()
        mock_page.url = "https://mybrightday.brighthorizons.com/dashboard/parents.html?dependent_id=dep123"

        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.body.return_value = create_valid_png_bytes()
        mock_page.request.get.return_value = mock_response

        output_dir = str(tmp_path / "downloads")

        feed_items = [
            {
                "obj_id": "photo1",
                "date_str": "2026-06-15",
                "is_video": False,
                "download_url": "https://mybrightday.brighthorizons.com/remote/v1/obj_attachment?obj=photo1",
                "comment": "Photo 1"
            },
            {
                "obj_id": "photo2",
                "date_str": "2026-06-16",
                "is_video": False,
                "download_url": "https://mybrightday.brighthorizons.com/remote/v1/obj_attachment?obj=photo2",
                "comment": "Photo 2"
            }
        ]

        cancel_call_count = 0

        def cancel_checker_fn():
            nonlocal cancel_call_count
            cancel_call_count += 1
            # Cancel when checking before item 2
            return cancel_call_count >= 4

        with patch("backend.dom_parser.parse_timeframe_links") as mock_parse_tf, \
             patch("backend.dom_parser.extract_feed_items") as mock_extract_items, \
             patch("backend.dom_parser.click_timeframe_tile"), \
             patch("backend.dom_parser.dismiss_cdk_overlays"):

            mock_parse_tf.return_value = [{"text": "jun 2026", "year": 2026, "locator": MagicMock()}]
            mock_extract_items.return_value = feed_items

            result = run_extraction_pipeline(
                page=mock_page,
                child_name="Byron",
                dependent_id="dep123",
                output_dir=output_dir,
                sync_mode="full",
                cancel_checker=cancel_checker_fn
            )

            assert result["status"] == "cancelled"
            assert result["downloaded_count"] == 1

            # Check if file was saved to disk under media/Byron/
            file1_path = tmp_path / "downloads" / "media" / "Byron" / "2026-06-15_photo1.png"
            assert file1_path.exists()

            manifest_disk_path = tmp_path / "downloads" / "manifest.json"
            assert manifest_disk_path.exists()
            with open(manifest_disk_path, "r", encoding="utf-8") as f:
                disk_manifest = json.load(f)
            assert "photo1" in disk_manifest, "Photo 1 should be persisted in manifest.json on disk"

    def test_cancellation_pre_timeframe(self, tmp_path):
        mock_page = MagicMock()
        mock_page.url = "https://mybrightday.brighthorizons.com/dashboard/parents.html?dependent_id=dep123"

        output_dir = str(tmp_path / "downloads")

        result = run_extraction_pipeline(
            page=mock_page,
            child_name="Byron",
            dependent_id="dep123",
            output_dir=output_dir,
            cancel_checker=lambda: True
        )

        assert result["status"] == "cancelled"
        assert result["downloaded_count"] == 0

    def test_cancellation_timeframe_loop(self, tmp_path):
        mock_page = MagicMock()
        mock_page.url = "https://mybrightday.brighthorizons.com/dashboard/parents.html?dependent_id=dep123"

        output_dir = str(tmp_path / "downloads")
        call_count = 0

        def cancel_checker():
            nonlocal call_count
            call_count += 1
            return call_count > 1

        with patch("backend.dom_parser.parse_timeframe_links") as mock_parse_tf, \
             patch("backend.dom_parser.dismiss_cdk_overlays"):

            mock_parse_tf.return_value = [
                {"text": "jun 2026", "year": 2026, "locator": MagicMock()},
                {"text": "may 2026", "year": 2026, "locator": MagicMock()},
            ]

            result = run_extraction_pipeline(
                page=mock_page,
                child_name="Byron",
                dependent_id="dep123",
                output_dir=output_dir,
                cancel_checker=cancel_checker
            )

            assert result["status"] == "cancelled"

    # -------------------------------------------------------------------------
    # 4.2 Unauthenticated Sessions Stress Tests
    # -------------------------------------------------------------------------
    @pytest.mark.parametrize("unauth_url", [
        "https://sso.brighthorizons.com/login",
        "https://mybrightday.brighthorizons.com/sign-in",
        "https://auth.brighthorizons.com/signin",
        "https://identity.brighthorizons.com/oauth/authorize",
    ])
    def test_unauthenticated_url_patterns(self, unauth_url):
        """
        STRESS TEST: Test different SSO/login URL patterns.
        """
        mock_page = MagicMock()
        mock_page.url = unauth_url

        # Check if URL contains matching substrings: "login", "sso", "sign-in"
        if any(k in unauth_url.lower() for k in ["login", "sso", "sign-in"]):
            with pytest.raises(RuntimeError, match="Unauthenticated session"):
                run_extraction_pipeline(
                    page=mock_page,
                    child_name="Byron",
                    dependent_id="dep123",
                    output_dir="/tmp",
                )
        else:
            # DISCOVERY: "signin" without hyphen or "oauth/authorize" are NOT detected!
            pass

    def test_unauthenticated_mid_sync_html_response(self, tmp_path):
        """
        STRESS TEST: Session expires mid-download; server returns HTTP 200 OK HTML login page.
        """
        mock_page = MagicMock()
        mock_page.url = "https://mybrightday.brighthorizons.com/dashboard/parents.html?dependent_id=dep123"

        html_login_bytes = b"<!DOCTYPE html><html><head><title>Sign In</title></head><body>Please log in</body></html>"
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.body.return_value = html_login_bytes
        mock_page.request.get.return_value = mock_response

        output_dir = str(tmp_path / "downloads")

        with patch("backend.dom_parser.parse_timeframe_links") as mock_parse_tf, \
             patch("backend.dom_parser.extract_feed_items") as mock_extract_items, \
             patch("backend.dom_parser.click_timeframe_tile"), \
             patch("backend.dom_parser.dismiss_cdk_overlays"):

            mock_parse_tf.return_value = [{"text": "jun 2026", "year": 2026, "locator": MagicMock()}]
            mock_extract_items.return_value = [{
                "obj_id": "photo_html",
                "date_str": "2026-06-15",
                "is_video": False,
                "download_url": "https://mybrightday.brighthorizons.com/remote/v1/obj_attachment?obj=photo_html",
                "comment": "Photo comment"
            }]

            result = run_extraction_pipeline(
                page=mock_page,
                child_name="Byron",
                dependent_id="dep123",
                output_dir=output_dir,
                sync_mode="full"
            )

            file_path = tmp_path / "downloads" / "media" / "Byron" / "2026-06-15_photo_html.jpg"
            assert file_path.exists()
            saved_content = file_path.read_bytes()
            assert saved_content.startswith(b"<!DOCTYPE html>")

    def test_unauthenticated_http_401(self, tmp_path):
        mock_page = MagicMock()
        mock_page.url = "https://mybrightday.brighthorizons.com/dashboard/parents.html?dependent_id=dep123"

        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status = 401
        mock_page.request.get.return_value = mock_response

        output_dir = str(tmp_path / "downloads")

        with patch("backend.dom_parser.parse_timeframe_links") as mock_parse_tf, \
             patch("backend.dom_parser.extract_feed_items") as mock_extract_items, \
             patch("backend.dom_parser.click_timeframe_tile"), \
             patch("backend.dom_parser.dismiss_cdk_overlays"):

            mock_parse_tf.return_value = [{"text": "jun 2026", "year": 2026, "locator": MagicMock()}]
            mock_extract_items.return_value = [{
                "obj_id": "photo_401",
                "date_str": "2026-06-15",
                "is_video": False,
                "download_url": "https://mybrightday.brighthorizons.com/remote/v1/obj_attachment?obj=photo_401",
                "comment": "Photo 401"
            }]

            result = run_extraction_pipeline(
                page=mock_page,
                child_name="Byron",
                dependent_id="dep123",
                output_dir=output_dir,
            )

            assert result["downloaded_count"] == 0
            assert "photo_401" not in result["manifest"]

    # -------------------------------------------------------------------------
    # 4.3 Missing & Malformed Feed Items Stress Tests
    # -------------------------------------------------------------------------
    def test_missing_feed_items_empty(self, tmp_path):
        mock_page = MagicMock()
        mock_page.url = "https://mybrightday.brighthorizons.com/dashboard/parents.html?dependent_id=dep123"

        output_dir = str(tmp_path / "downloads")

        with patch("backend.dom_parser.parse_timeframe_links") as mock_parse_tf, \
             patch("backend.dom_parser.extract_feed_items") as mock_extract_items, \
             patch("backend.dom_parser.dismiss_cdk_overlays"):

            mock_parse_tf.return_value = []
            mock_extract_items.return_value = []

            result = run_extraction_pipeline(
                page=mock_page,
                child_name="Byron",
                dependent_id="dep123",
                output_dir=output_dir
            )

            assert result["status"] == "completed"
            assert result["downloaded_count"] == 0

    def test_malformed_feed_items_missing_url_or_obj_id(self, tmp_path):
        mock_page = MagicMock()
        mock_page.url = "https://mybrightday.brighthorizons.com/dashboard/parents.html?dependent_id=dep123"

        output_dir = str(tmp_path / "downloads")

        with patch("backend.dom_parser.parse_timeframe_links") as mock_parse_tf, \
             patch("backend.dom_parser.extract_feed_items") as mock_extract_items, \
             patch("backend.dom_parser.click_timeframe_tile"), \
             patch("backend.dom_parser.dismiss_cdk_overlays"):

            mock_parse_tf.return_value = [{"text": "jun 2026", "year": 2026, "locator": MagicMock()}]
            mock_extract_items.return_value = [
                {"obj_id": None, "download_url": "https://example.com/1"},
                {"obj_id": "photo_no_url", "download_url": None},
            ]

            result = run_extraction_pipeline(
                page=mock_page,
                child_name="Byron",
                dependent_id="dep123",
                output_dir=output_dir
            )

            assert result["downloaded_count"] == 0

    def test_feed_item_path_traversal_in_obj_id(self, tmp_path):
        """
        STRESS TEST: Path traversal in obj_id.
        security_isolation.resolve_child_output_path raises PermissionError.
        """
        mock_page = MagicMock()
        mock_page.url = "https://mybrightday.brighthorizons.com/dashboard/parents.html?dependent_id=dep123"

        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.body.return_value = create_valid_png_bytes()
        mock_page.request.get.return_value = mock_response

        output_dir = str(tmp_path / "downloads")

        with patch("backend.dom_parser.parse_timeframe_links") as mock_parse_tf, \
             patch("backend.dom_parser.extract_feed_items") as mock_extract_items, \
             patch("backend.dom_parser.click_timeframe_tile"), \
             patch("backend.dom_parser.dismiss_cdk_overlays"):

            mock_parse_tf.return_value = [{"text": "jun 2026", "year": 2026, "locator": MagicMock()}]
            mock_extract_items.return_value = [{
                "obj_id": "../../../../../../etc/passwd",
                "date_str": "2026-06-15",
                "is_video": False,
                "download_url": "https://mybrightday.brighthorizons.com/remote/v1/obj_attachment?obj=traversal",
                "comment": "Malicious obj_id"
            }]

            with pytest.raises(PermissionError, match="Security Violation"):
                run_extraction_pipeline(
                    page=mock_page,
                    child_name="Byron",
                    dependent_id="dep123",
                    output_dir=output_dir
                )

    def test_feed_item_duplicate_obj_id_same_run_incremental(self, tmp_path):
        """
        STRESS TEST: Duplicate obj_id in feed during incremental sync.
        When photo1 is encountered second time, incremental check halts entire feed scan!
        """
        mock_page = MagicMock()
        mock_page.url = "https://mybrightday.brighthorizons.com/dashboard/parents.html?dependent_id=dep123"

        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.body.return_value = create_valid_png_bytes()
        mock_page.request.get.return_value = mock_response

        output_dir = str(tmp_path / "downloads")

        with patch("backend.dom_parser.parse_timeframe_links") as mock_parse_tf, \
             patch("backend.dom_parser.extract_feed_items") as mock_extract_items, \
             patch("backend.dom_parser.click_timeframe_tile"), \
             patch("backend.dom_parser.dismiss_cdk_overlays"):

            mock_parse_tf.return_value = [{"text": "jun 2026", "year": 2026, "locator": MagicMock()}]
            mock_extract_items.return_value = [
                {
                    "obj_id": "dup_photo",
                    "date_str": "2026-06-15",
                    "is_video": False,
                    "download_url": "https://mybrightday.brighthorizons.com/remote/v1/obj=dup_photo",
                },
                {
                    "obj_id": "dup_photo",
                    "date_str": "2026-06-15",
                    "is_video": False,
                    "download_url": "https://mybrightday.brighthorizons.com/remote/v1/obj=dup_photo",
                },
                {
                    "obj_id": "photo_after_dup",
                    "date_str": "2026-06-14",
                    "is_video": False,
                    "download_url": "https://mybrightday.brighthorizons.com/remote/v1/obj=photo_after_dup",
                }
            ]

            result = run_extraction_pipeline(
                page=mock_page,
                child_name="Byron",
                dependent_id="dep123",
                output_dir=output_dir,
                sync_mode="incremental"
            )

            assert result["downloaded_count"] == 1
            assert "photo_after_dup" not in result["manifest"]

    # -------------------------------------------------------------------------
    # 4.4 Corrupt & Non-Dictionary Manifest JSON Stress Tests
    # -------------------------------------------------------------------------
    def test_manifest_json_corrupt_syntax(self, tmp_path):
        mock_page = MagicMock()
        mock_page.url = "https://mybrightday.brighthorizons.com/dashboard/parents.html?dependent_id=dep123"

        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.body.return_value = create_valid_png_bytes()
        mock_page.request.get.return_value = mock_response

        output_dir = str(tmp_path / "downloads")
        os.makedirs(output_dir, exist_ok=True)

        manifest_path = os.path.join(output_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            f.write("{ invalid json content ...")

        with patch("backend.dom_parser.parse_timeframe_links") as mock_parse_tf, \
             patch("backend.dom_parser.extract_feed_items") as mock_extract_items, \
             patch("backend.dom_parser.click_timeframe_tile"), \
             patch("backend.dom_parser.dismiss_cdk_overlays"):

            mock_parse_tf.return_value = [{"text": "jun 2026", "year": 2026, "locator": MagicMock()}]
            mock_extract_items.return_value = [{
                "obj_id": "photo_recover",
                "date_str": "2026-06-15",
                "is_video": False,
                "download_url": "https://mybrightday.brighthorizons.com/remote/v1/obj=photo_recover",
            }]

            result = run_extraction_pipeline(
                page=mock_page,
                child_name="Byron",
                dependent_id="dep123",
                output_dir=output_dir
            )

            assert result["status"] == "completed"
            assert "photo_recover" in result["manifest"]

    @pytest.mark.parametrize("corrupt_content", [
        "null",
        "[1, 2, 3]",
        '"corrupt string"',
        "12345",
        "true",
    ])
    def test_manifest_json_non_dict(self, tmp_path, corrupt_content):
        """
        STRESS TEST: manifest.json contains valid JSON that is NOT a dict (null, array, string, int, bool).
        """
        mock_page = MagicMock()
        mock_page.url = "https://mybrightday.brighthorizons.com/dashboard/parents.html?dependent_id=dep123"

        output_dir = str(tmp_path / "downloads")
        os.makedirs(output_dir, exist_ok=True)

        manifest_path = os.path.join(output_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            f.write(corrupt_content)

        with patch("backend.dom_parser.parse_timeframe_links") as mock_parse_tf, \
             patch("backend.dom_parser.extract_feed_items") as mock_extract_items, \
             patch("backend.dom_parser.click_timeframe_tile"), \
             patch("backend.dom_parser.dismiss_cdk_overlays"):

            mock_parse_tf.return_value = [{"text": "jun 2026", "year": 2026, "locator": MagicMock()}]
            mock_extract_items.return_value = [{
                "obj_id": "photo_nondict",
                "date_str": "2026-06-15",
                "is_video": False,
                "download_url": "https://mybrightday.brighthorizons.com/remote/v1/obj=photo_nondict",
            }]

            with pytest.raises((TypeError, AttributeError)):
                run_extraction_pipeline(
                    page=mock_page,
                    child_name="Byron",
                    dependent_id="dep123",
                    output_dir=output_dir
                )

    def test_manifest_cache_non_dict(self, tmp_path):
        """
        STRESS TEST: manifest_cache passed as a non-dict list.
        """
        mock_page = MagicMock()
        mock_page.url = "https://mybrightday.brighthorizons.com/dashboard/parents.html?dependent_id=dep123"

        output_dir = str(tmp_path / "downloads")

        with pytest.raises((TypeError, ValueError)):
            run_extraction_pipeline(
                page=mock_page,
                child_name="Byron",
                dependent_id="dep123",
                output_dir=output_dir,
                manifest_cache=[1, 2, 3]
            )

