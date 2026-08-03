# SPDX-License-Identifier: MIT
"""
Adversarial empirical stress-test suite for backend/dom_parser.py.
Tests edge cases, malformed HTML, video CSS variations, missing feed containers,
and unexpected date/month string formats.
"""

import pytest
from unittest.mock import MagicMock
from backend.dom_parser import (
    is_valid_timeframe_text,
    parse_date_overlay,
    extract_obj_id_from_url_or_style,
    parse_timeframe_links,
    click_timeframe_tile,
    extract_feed_items,
    discover_children_from_family_info,
    dismiss_cdk_overlays
)


# =============================================================================
# Category 1: Timeframe String Parsing & Validation Stress Tests
# =============================================================================

class TestTimeframeParsingAdversarial:
    """Stress tests for is_valid_timeframe_text and parse_timeframe_links."""

    @pytest.mark.parametrize("valid_input", [
        "jun 2026",
        "NOV 2024",
        "  dec 2025  ",
        "jan 2020",
        "feb\xa02026",  # non-breaking space
        "mar\t2026",   # tab
        "apr   2026",  # multiple spaces
    ])
    def test_valid_timeframe_strings(self, valid_input):
        assert is_valid_timeframe_text(valid_input) is True

    @pytest.mark.parametrize("invalid_input", [
        "Selected Jun 2026 (12 items)",
        "All Months",
        "2026",
        "",
        None,
        12345,
        ["jun", "2026"],
        "June 2026",       # 4 letters
        "july 2026",       # 4 letters
        "sept 2026",       # 4 letters
        "jun 202",         # 3 digits year
        "jun 20261",       # 5 digits year
        "jun -2026",       # negative year
        "month jun 2026",  # prefix
        "jun 2026 month",  # suffix
    ])
    def test_invalid_timeframe_strings(self, invalid_input):
        assert is_valid_timeframe_text(invalid_input) is False

    @pytest.mark.parametrize("non_month_3letter_word", [
        "foo 2026",
        "all 2026",
        "cat 2025",
        "xyz 2024",
        "bar 2023",
        "top 2022",
    ])
    def test_non_month_3letter_words_regex_flaw(self, non_month_3letter_word):
        """
        Verifies non-month 3-letter words are strictly rejected by TIMEFRAME_REGEX.
        """
        is_valid = is_valid_timeframe_text(non_month_3letter_word)
        assert is_valid is False

    def test_parse_timeframe_links_fallback_behavior_for_non_month(self):
        """
        Verifies parse_timeframe_links rejects non-month strings like 'foo 2026'.
        """
        mock_page = MagicMock()
        mock_li = MagicMock()
        mock_li.inner_text.return_value = "foo 2026"
        mock_tile = MagicMock()
        mock_tile.count.return_value = 1
        mock_li.locator.return_value.first = mock_tile
        mock_page.locator.return_value.all.return_value = [mock_li]

        items = parse_timeframe_links(mock_page)
        assert len(items) == 0


# =============================================================================
# Category 2: Date Overlay Parsing Stress Tests
# =============================================================================

class TestDateOverlayParsingAdversarial:
    """Stress tests for parse_date_overlay."""

    def test_standard_date_formats(self):
        assert parse_date_overlay("6/15", timeframe_year=2026) == "2026-06-15"
        assert parse_date_overlay("06/15/2025") == "2025-06-15"
        assert parse_date_overlay("6/15/26") == "2026-06-15"
        assert parse_date_overlay("12/31", timeframe_year=2024) == "2024-12-31"

    @pytest.mark.parametrize("date_format,expected_iso", [
        ("2026-06-15", "2026-06-15"),
        ("Jun 15, 2026", "2026-06-15"),
        ("Jun 15", "2026-06-15"),
        ("15 Jun 2026", "2026-06-15"),
        ("6/15/2026 10:00 AM", "2026-06-15"),
        ("6.15.2026", "2026-06-15"),
        ("6-15-2026", "2026-06-15"),
    ])
    def test_enhanced_date_string_formats(self, date_format, expected_iso):
        """
        Verifies parse_date_overlay correctly parses ISO, textual month, dot/dash, and datetime formats.
        """
        result = parse_date_overlay(date_format, timeframe_year=2026)
        assert result == expected_iso

    def test_relative_date_string_formats(self):
        """Verifies parse_date_overlay handles 'Today' and 'Yesterday' relative date strings."""
        res_today = parse_date_overlay("Today", timeframe_year=2026)
        assert res_today.startswith("2026-")

        res_yesterday = parse_date_overlay("Yesterday", timeframe_year=2026)
        assert res_yesterday.startswith("2026-")

    @pytest.mark.parametrize("invalid_numerical_date", [
        "99/99",
        "00/00",
        "13/45",
    ])
    def test_invalid_numerical_calendar_dates(self, invalid_numerical_date):
        """
        Verifies parse_date_overlay enforces valid month (1-12) and day (1-31) ranges.
        Out-of-range dates fall back to default valid date instead of returning invalid month/day values.
        """
        res = parse_date_overlay(invalid_numerical_date, timeframe_year=2026)
        assert res.startswith("2026-")
        parts = res.split("-")
        assert 1 <= int(parts[1]) <= 12
        assert 1 <= int(parts[2]) <= 31

    def test_three_digit_year_parsing(self):
        """Test how parse_date_overlay handles 3-digit years like 6/15/202."""
        res = parse_date_overlay("6/15/202", timeframe_year=2026)
        assert res == "0202-06-15"

    def test_empty_or_none_or_garbage_date_overlay(self):
        res_none = parse_date_overlay(None, timeframe_year=2026)
        assert res_none.startswith("2026-")

        res_empty = parse_date_overlay("", timeframe_year=2026)
        assert res_empty.startswith("2026-")

        res_space = parse_date_overlay("   ", timeframe_year=2026)
        assert res_space.startswith("2026-")


# =============================================================================
# Category 3: Video & Photo URL/Style Parsing Stress Tests
# =============================================================================

class TestExtractObjIdAdversarial:
    """Stress tests for extract_obj_id_from_url_or_style."""

    def test_photo_standard(self):
        photo_href = "/remote/v1/obj_attachment?obj=12345&amp;key=12345"
        obj_id, is_video, resolved = extract_obj_id_from_url_or_style(photo_href, "")
        assert obj_id == "12345"
        assert is_video is False
        assert resolved == "/remote/v1/obj_attachment?obj=12345&key=12345"

    def test_video_standard_anchor_and_style(self):
        video_href = "#6986168d2bb117b0dc910b3b-default"
        video_style = "background-image: url('/remote/v1/obj_attachment?obj=6986168d2bb117b0dc910b3b&amp;key=6986168d2bb117b0dc910b3b');"
        obj_id, is_video, resolved = extract_obj_id_from_url_or_style(video_href, video_style)
        assert obj_id == "6986168d2bb117b0dc910b3b"
        assert is_video is True

    @pytest.mark.parametrize("uppercase_style", [
        "BACKGROUND-IMAGE: URL('/remote/v1/obj_attachment?obj=vid999&amp;key=vid999');",
        "Background-Image: Url(\"/remote/v1/obj_attachment?obj=vid999\");",
    ])
    def test_uppercase_url_in_css(self, uppercase_style):
        """
        Verifies re.search is case-insensitive when matching CSS url(...).
        """
        href = "#video-id"
        obj_id, is_video, resolved = extract_obj_id_from_url_or_style(href, uppercase_style)
        assert is_video is True
        assert obj_id == "vid999"

    def test_spaces_inside_css_url(self):
        style = "background-image: url( /remote/v1/obj_attachment?obj=vid888 );"
        href = "#vid"
        obj_id, is_video, resolved = extract_obj_id_from_url_or_style(href, style)
        assert is_video is True
        assert obj_id == "vid888"

    def test_multiple_urls_in_css_background(self):
        """When multiple background image URLs exist in CSS style, iterates to find obj_attachment."""
        style = "background: url('/images/overlay.png'), url('/remote/v1/obj_attachment?obj=vid777');"
        href = "#vid"
        obj_id, is_video, resolved = extract_obj_id_from_url_or_style(href, style)
        assert is_video is True
        assert obj_id == "vid777"
        assert "obj=vid777" in resolved


    def test_html_entities_in_style(self):
        style = "background-image: url(&quot;/remote/v1/obj_attachment?obj=vid666&amp;key=vid666&quot;);"
        href = "#vid"
        obj_id, is_video, resolved = extract_obj_id_from_url_or_style(href, style)
        assert is_video is True
        assert obj_id == "vid666"

    def test_non_obj_attachment_photo_href(self):
        """
        Verifies photo posts with alternative endpoint URLs containing obj= parameter are not misclassified as video.
        """
        href = "/remote/v1/media?obj=p555"
        obj_id, is_video, resolved = extract_obj_id_from_url_or_style(href, "")
        assert obj_id == "p555"
        assert is_video is False

    def test_obj_id_with_trailing_fragments_or_params(self):
        href = "/remote/v1/obj_attachment?obj=p444#section&key=p444"
        obj_id, is_video, resolved = extract_obj_id_from_url_or_style(href, "")
        assert obj_id == "p444"


# =============================================================================
# Category 4: Playwright DOM Scoping & Feed Extraction Stress Tests
# =============================================================================

class TestExtractFeedItemsAdversarial:
    """Stress tests for extract_feed_items Playwright scoping and malformed DOM."""

    def test_feed_items_missing_timeline_well(self):
        """Rule 2.B enforcement: Returns [] immediately if div.well.left-panel.pull-left absent."""
        mock_page = MagicMock()
        mock_timeline = MagicMock()
        mock_timeline.count.return_value = 0
        mock_page.locator.return_value = mock_timeline

        items = extract_feed_items(mock_page)
        assert items == []

    def test_feed_items_malformed_lis_resilience(self):
        """Ensures corrupted or incomplete <li> elements inside feed do not crash extraction."""
        mock_page = MagicMock()
        mock_timeline = MagicMock()
        mock_timeline.count.return_value = 1
        mock_page.locator.return_value = mock_timeline

        # Mock 3 items: 1 malformed (no fancybox), 1 invalid (no obj_id), 1 valid
        mock_li1 = MagicMock()
        mock_fb1 = MagicMock()
        mock_fb1.count.return_value = 0
        mock_li1.locator.return_value.first = mock_fb1

        mock_li2 = MagicMock()
        mock_fb2 = MagicMock()
        mock_fb2.count.return_value = 1
        mock_fb2.get_attribute.return_value = "#no-obj-here"
        mock_tile2 = MagicMock()
        mock_tile2.count.return_value = 0
        mock_tile2.get_attribute.return_value = ""

        def loc2_side_effect(sel):
            if sel == "a.fancybox":
                return MagicMock(first=mock_fb2)
            if sel == "div.tile.pointable, div.tile":
                return MagicMock(first=mock_tile2)
            return MagicMock()
        mock_li2.locator.side_effect = loc2_side_effect

        mock_li3 = MagicMock()
        mock_fb3 = MagicMock()
        mock_fb3.count.return_value = 1
        mock_fb3.get_attribute.return_value = "/remote/v1/obj_attachment?obj=p999"
        mock_tile3 = MagicMock()
        mock_tile3.count.return_value = 0
        mock_tile3.get_attribute.return_value = ""
        mock_span3 = MagicMock()
        mock_span3.count.return_value = 1
        mock_span3.inner_text.return_value = "7/31"

        def loc3_side_effect(sel):
            if sel == "a.fancybox":
                return MagicMock(first=mock_fb3)
            if sel == "div.tile.pointable, div.tile":
                return MagicMock(first=mock_tile3)
            if sel == "span.name span":
                return MagicMock(first=mock_span3)
            return MagicMock()
        mock_li3.locator.side_effect = loc3_side_effect

        mock_timeline.locator.return_value.all.return_value = [mock_li1, mock_li2, mock_li3]

        items = extract_feed_items(mock_page, timeframe_year=2026)
        assert len(items) == 1
        assert items[0]["obj_id"] == "p999"
        assert items[0]["date_str"] == "2026-07-31"


# =============================================================================
# Category 5: Angular CDK Auto-Discovery Stress Tests
# =============================================================================

class TestDiscoverChildrenAdversarial:
    """Stress tests for discover_children_from_family_info."""

    def test_child_without_active_enrollment_handled_gracefully(self):
        """Rule 5: Unenrolled child causes wait_for to time out, should log and skip cleanly."""
        mock_page = MagicMock()
        mock_context = MagicMock()
        mock_page.url = "https://familyinfocenter.brighthorizons.com/home"

        mock_span = MagicMock()
        mock_span.evaluate.return_value = "Graduated Child"
        mock_page.locator.return_value.all.return_value = [mock_span]

        # My Bright Day menu item times out (not visible)
        mock_mbd_item = MagicMock()
        mock_mbd_item.wait_for.side_effect = Exception("Timeout waiting for element")
        mock_page.locator.return_value.first = mock_mbd_item

        logger_messages = []
        children = discover_children_from_family_info(mock_page, mock_context, logger=logger_messages.append)

        assert children == []
        assert any("no active My Bright Day enrollment" in m for m in logger_messages)
