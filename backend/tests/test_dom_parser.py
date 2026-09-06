# SPDX-License-Identifier: MIT
"""
Unit tests for backend/dom_parser.py.
"""

from unittest.mock import MagicMock
from backend.dom_parser import (
    is_valid_timeframe_text,
    parse_date_overlay,
    extract_obj_id_from_url_or_style,
    parse_timeframe_links,
    click_timeframe_tile,
    extract_feed_items,
    discover_children_from_family_info,
    discover_children_from_parents_params,
    dismiss_cdk_overlays
)

def test_is_valid_timeframe_text():
    assert is_valid_timeframe_text("jun 2026") is True
    assert is_valid_timeframe_text("NOV 2024") is True
    assert is_valid_timeframe_text("  dec 2025  ") is True
    assert is_valid_timeframe_text("jan 2020") is True

    # Invalid patterns
    assert is_valid_timeframe_text("Selected Jun 2026 (12 items)") is False
    assert is_valid_timeframe_text("All Months") is False
    assert is_valid_timeframe_text("2026") is False
    assert is_valid_timeframe_text("") is False
    assert is_valid_timeframe_text(None) is False
    assert is_valid_timeframe_text("June 2026") is False  # 4 letters


def test_parse_date_overlay():
    assert parse_date_overlay("6/15", timeframe_year=2026) == "2026-06-15"
    assert parse_date_overlay("06/15/2025") == "2025-06-15"
    assert parse_date_overlay("6/15/26") == "2026-06-15"
    assert parse_date_overlay("12/31", timeframe_year=2024) == "2024-12-31"

    # Fallback default
    res_empty = parse_date_overlay("", timeframe_year=2026)
    assert res_empty.startswith("2026-")


def test_extract_obj_id_from_url_or_style():
    # Photo post with raw href containing HTML entity &amp;
    photo_href = "/remote/v1/obj_attachment?obj=12345&amp;key=12345"
    obj_id, is_video, resolved = extract_obj_id_from_url_or_style(photo_href, "")
    assert obj_id == "12345"
    assert is_video is False
    assert resolved == "/remote/v1/obj_attachment?obj=12345&key=12345"

    # Video post with anchor href and style attribute background-image
    video_href = "#6986168d2bb117b0dc910b3b-default"
    video_style = "background-image: url('/remote/v1/obj_attachment?obj=6986168d2bb117b0dc910b3b&amp;key=6986168d2bb117b0dc910b3b');"
    obj_id, is_video, resolved = extract_obj_id_from_url_or_style(video_href, video_style)
    assert obj_id == "6986168d2bb117b0dc910b3b"
    assert is_video is True
    assert "obj=6986168d2bb117b0dc910b3b" in resolved

    # Invalid post (no obj parameter)
    obj_id, is_video, resolved = extract_obj_id_from_url_or_style("#invalid", "color: red;")
    assert obj_id is None
    assert is_video is True


def test_parse_timeframe_links_mock():
    mock_page = MagicMock()

    mock_li1 = MagicMock()
    mock_li1.inner_text.return_value = "jun 2026"
    mock_tile1 = MagicMock()
    mock_tile1.count.return_value = 1
    mock_li1.locator.return_value.first = mock_tile1

    mock_li2 = MagicMock()
    mock_li2.inner_text.return_value = "invalid text"

    mock_li3 = MagicMock()
    mock_li3.inner_text.return_value = "nov 2024"
    mock_tile3 = MagicMock()
    mock_tile3.count.return_value = 0
    mock_li3.locator.return_value.first = mock_tile3

    mock_page.locator.return_value.all.return_value = [mock_li1, mock_li2, mock_li3]

    items = parse_timeframe_links(mock_page)
    assert len(items) == 2

    assert items[0]["text"] == "jun 2026"
    assert items[0]["year"] == 2026
    assert items[0]["month"] == 6
    assert items[0]["tile_locator"] == mock_tile1

    assert items[1]["text"] == "nov 2024"
    assert items[1]["year"] == 2024
    assert items[1]["month"] == 11
    assert items[1]["tile_locator"] == mock_li3


def test_click_timeframe_tile_mock():
    mock_page = MagicMock()

    # Test with dict input containing tile_locator
    mock_tile = MagicMock()
    tf_item = {"tile_locator": mock_tile}
    res = click_timeframe_tile(mock_page, tf_item)
    assert res is True
    mock_tile.click.assert_called_once()

    # Test with direct locator input
    mock_direct_loc = MagicMock()
    res2 = click_timeframe_tile(mock_page, mock_direct_loc)
    assert res2 is True
    mock_direct_loc.click.assert_called_once()


def test_extract_feed_items_scoping_mock():
    mock_page = MagicMock()
    mock_timeline = MagicMock()

    # Test strict Rule 2.B scoping: timeline absent
    mock_timeline.count.return_value = 0
    mock_page.locator.return_value = mock_timeline

    items = extract_feed_items(mock_page)
    assert items == []  # Must return empty list, not call global locator!

    # Test when timeline present
    mock_timeline.count.return_value = 1

    mock_item1 = MagicMock()
    mock_fancybox1 = MagicMock()
    mock_fancybox1.count.return_value = 1
    mock_fancybox1.get_attribute.return_value = "/remote/v1/obj_attachment?obj=p100"

    mock_tile = MagicMock()
    mock_tile.count.return_value = 0
    mock_tile.get_attribute.return_value = ""

    mock_span = MagicMock()
    mock_span.count.return_value = 1
    mock_span.inner_text.return_value = "6/10"

    def item_locator_side_effect(sel):
        if sel == "a.fancybox":
            return MagicMock(first=mock_fancybox1)
        elif sel == "div.tile.pointable, div.tile":
            return MagicMock(first=mock_tile)
        elif sel == "span.name span":
            return MagicMock(first=mock_span)
        return MagicMock()

    mock_item1.locator.side_effect = item_locator_side_effect
    mock_timeline.locator.return_value.all.return_value = [mock_item1]

    parsed = extract_feed_items(mock_page, timeframe_year=2026)
    assert len(parsed) == 1
    assert parsed[0]["obj_id"] == "p100"
    assert parsed[0]["media_type"] == "photo"
    assert parsed[0]["date_str"] == "2026-06-10"


def test_discover_children_from_family_info_mock():
    mock_page = MagicMock()
    mock_context = MagicMock()
    mock_page.url = "https://familyinfocenter.brighthorizons.com/home"

    mock_card = MagicMock()
    mock_title_locator = MagicMock()
    mock_title_locator.inner_text.return_value = "Byron Taccani Massarelli"
    mock_title_locator.wait_for.return_value = None
    
    mock_trigger_locator = MagicMock()
    
    def mock_card_locator(selector, **kwargs):
        mock_loc = MagicMock()
        if "card-title" in selector:
            mock_loc.first = mock_title_locator
        else:
            mock_loc.first = mock_trigger_locator
        return mock_loc

    mock_card.locator.side_effect = mock_card_locator

    mock_page.locator.return_value.all.return_value = [mock_card]

    mock_mbd_item = MagicMock()
    mock_mbd_item.wait_for.return_value = None
    mock_page.locator.return_value.first = mock_mbd_item

    mock_new_page = MagicMock()
    mock_new_page.url = "https://mybrightday.brighthorizons.com/dashboard/parents.html?dependent_id=673e065a9d37c9fab2483b2d"

    mock_expect_context = MagicMock()
    mock_expect_context.value = mock_new_page
    mock_context.expect_page.return_value.__enter__.return_value = mock_expect_context

    children = discover_children_from_family_info(mock_page, mock_context)
    assert len(children) == 1
    assert children[0]["name"] == "Byron"
    assert children[0]["given_name"] == "Byron"
    assert children[0]["full_name"] == "Byron Taccani Massarelli"
    assert children[0]["dependent_id"] == "673e065a9d37c9fab2483b2d"


def test_dismiss_cdk_overlays():
    mock_page = MagicMock()
    mock_page.locator.return_value.count.return_value = 1
    dismiss_cdk_overlays(mock_page)
    mock_page.keyboard.press.assert_called_with("Escape")


def test_extract_obj_id_from_direct_gcs_photo_url():
    gcs_photo_href = "https://storage.googleapis.com/mbd-attachments-prod/6a073ebd6be647694dacbdfb/main.jpg?X-Goog-Algorithm=GOOG4-RSA-SHA256&X-Goog-Credential=foo"
    obj_id, is_video, resolved_url = extract_obj_id_from_url_or_style(href=gcs_photo_href)
    assert obj_id == "6a073ebd6be647694dacbdfb"
    assert is_video is False
    assert resolved_url == gcs_photo_href


def test_extract_obj_id_from_direct_gcs_video_rel_url():
    video_href = "#6a020ff419db06fe02ab35af-default"
    gcs_video_rel = "https://storage.googleapis.com/mbd-attachments-prod/6a020ff419db06fe02ab35ae/main.mp4?X-Goog-Algorithm=GOOG4-RSA-SHA256&X-Goog-Credential=foo"
    obj_id, is_video, resolved_url = extract_obj_id_from_url_or_style(href=video_href, rel=gcs_video_rel)
    assert obj_id == "6a020ff419db06fe02ab35ae"
    assert is_video is True
    assert resolved_url == gcs_video_rel


import pytest
from backend.dom_parser import check_month_busy_state, wait_for_month_feed_ready

def test_check_month_busy_state_mock():
    mock_page = MagicMock()
    mock_page.evaluate.return_value = True
    assert check_month_busy_state(mock_page) is True

    mock_page.evaluate.return_value = False
    assert check_month_busy_state(mock_page) is False


def test_wait_for_month_feed_ready_empty_month():
    mock_page = MagicMock()
    # 1st evaluate (busy check): returns False (not busy)
    # 2nd evaluate (no events visible check): returns True (empty month confirmed)
    mock_page.evaluate.side_effect = [False, True]

    res = wait_for_month_feed_ready(mock_page, "jun 2026", max_wait_sec=5.0)
    assert res is False
    assert mock_page.wait_for_timeout.call_count >= 2  # initial 2.5s and post-busy 3.5s


def test_wait_for_month_feed_ready_populated_month():
    mock_page = MagicMock()
    # 1st evaluate (busy check): False
    # 2nd evaluate (no events check): False
    # 3rd evaluate (feed readiness check): {totalCards: 3, readyCount: 3}
    mock_page.evaluate.side_effect = [False, False, {"totalCards": 3, "readyCount": 3}]

    res = wait_for_month_feed_ready(mock_page, "jun 2026", max_wait_sec=5.0)
    assert res is True


def test_wait_for_month_feed_ready_timeout_error():
    mock_page = MagicMock()
    mock_page.evaluate.return_value = True  # Always busy

    with pytest.raises(TimeoutError) as exc_info:
        wait_for_month_feed_ready(mock_page, "jun 2026", max_wait_sec=0.1)

    assert "Max wait time" in str(exc_info.value)
    assert "jun 2026" in str(exc_info.value)


def test_discover_children_from_parents_params_multi_center():
    mock_page = MagicMock()
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "children": [
            {
                "first_name": "Theodore",
                "last_name": "Weiss-Papaioannou",
                "key": "665a6a5e1baa04a19f8681ab",
                "attachment": "6a03594bebd79a252224a5af",
                "location_name": "River School West Side"
            },
            {
                "first_name": "Alice",
                "last_name": "Weiss-Papaioannou",
                "key": "6a84c09187e6316a97724f9a",
                "attachment": None,
                "location_name": "Bright Horizons at West 72nd"
            },
            {
                "first_name": "Theodore",
                "last_name": "Weiss-Papaioannou",
                "key": "6a84c09287e6316a97724f9e",
                "attachment": None,
                "location_name": "Bright Horizons at West 72nd"
            }
        ]
    }
    mock_page.request.get.return_value = mock_resp

    children = discover_children_from_parents_params(mock_page)
    assert len(children) == 3
    # Both Theodore center profiles preserved with same given name "Theodore"
    theodores = [c for c in children if c["name"] == "Theodore"]
    assert len(theodores) == 2
    assert theodores[0]["dependent_id"] == "665a6a5e1baa04a19f8681ab"
    assert theodores[0]["location_name"] == "River School West Side"
    assert theodores[0]["attachment_key"] == "6a03594bebd79a252224a5af"

    assert theodores[1]["dependent_id"] == "6a84c09287e6316a97724f9e"
    assert theodores[1]["location_name"] == "Bright Horizons at West 72nd"
    assert theodores[1]["attachment_key"] is None

    alices = [c for c in children if c["name"] == "Alice"]
    assert len(alices) == 1
    assert alices[0]["dependent_id"] == "6a84c09187e6316a97724f9a"


def test_discover_children_from_mybrightday_dom():
    from backend.dom_parser import discover_children_from_mybrightday_dom
    mock_page = MagicMock()
    mock_page.evaluate.return_value = [
        {"text": "All Kids", "imgAlt": "", "attKey": ""},
        {"text": "Byron", "imgAlt": "", "attKey": "att123"},
        {"text": "", "imgAlt": "Catherine", "attKey": "att456"},
        {"text": "Timeline", "imgAlt": "", "attKey": ""},
        {"text": "", "imgAlt": "", "attKey": ""}
    ]

    children = discover_children_from_mybrightday_dom(mock_page)
    assert len(children) == 2
    assert children[0]["name"] == "Byron"
    assert children[0]["attachment_key"] == "att123"
    assert children[0]["dependent_id"] == "all"
    assert children[1]["name"] == "Catherine"
    assert children[1]["attachment_key"] == "att456"
    assert children[1]["dependent_id"] == "all"


def test_exchange_mbd_jwt_token_success():
    from backend.dom_parser import exchange_mbd_jwt_token
    mock_page = MagicMock()
    mock_page.url = "https://familyinfocenter.brighthorizons.com/home"

    # evaluate called twice: first for token from localStorage, second for fetch to gateway
    mock_page.evaluate.side_effect = [
        "auth0_access_token_123",
        {"ok": True, "token": "jwt_token_xyz"}
    ]
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_page.request.get.return_value = mock_resp

    logs = []
    res = exchange_mbd_jwt_token(mock_page, dependent_id="dep_456", logger=logs.append)
    assert res is True
    assert any("Successfully minted fresh MBD JWT" in l for l in logs)
    assert any("Successfully established authenticated session" in l for l in logs)
    mock_page.goto.assert_called()
    called_url = mock_page.goto.call_args[0][0]
    assert "https://mybrightday.brighthorizons.com/auth/jwt/redirect" in called_url
    assert "jwt=jwt_token_xyz" in called_url
    assert "childid=dep_456" in called_url


def test_exchange_mbd_jwt_token_missing_token():
    from backend.dom_parser import exchange_mbd_jwt_token
    mock_page = MagicMock()
    mock_page.url = "https://familyinfocenter.brighthorizons.com/home"
    mock_page.evaluate.return_value = None

    logs = []
    res = exchange_mbd_jwt_token(mock_page, logger=logs.append)
    assert res is False
    assert any("No access_token found" in l for l in logs)


def test_exchange_mbd_jwt_token_gateway_failure():
    from backend.dom_parser import exchange_mbd_jwt_token
    mock_page = MagicMock()
    mock_page.url = "https://familyinfocenter.brighthorizons.com/home"
    mock_page.evaluate.side_effect = [
        "auth0_access_token_123",
        {"ok": False, "status": 401, "text": "Unauthorized"}
    ]

    logs = []
    res = exchange_mbd_jwt_token(mock_page, logger=logs.append)
    assert res is False
    assert any("Gateway mbdtoken request failed" in l for l in logs)





