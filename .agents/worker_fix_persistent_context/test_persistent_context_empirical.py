import json
import os
import pytest
from playwright.sync_api import sync_playwright, BrowserContext
from backend.scraper_engine import launch_stealth_persistent_context

def test_launch_stealth_persistent_context_with_existing_storage_state(tmp_path):
    """Verifies real Playwright launches persistent context without TypeError when storage_state.json exists."""
    user_data = tmp_path / "user_data"
    user_data.mkdir()
    state_file = user_data / "storage_state.json"
    dummy_state = {
        "cookies": [
            {
                "name": "test_cookie",
                "value": "12345",
                "domain": ".example.com",
                "path": "/",
                "expires": -1,
                "httpOnly": False,
                "secure": True,
                "sameSite": "Lax"
            }
        ],
        "origins": []
    }
    state_file.write_text(json.dumps(dummy_state))

    with sync_playwright() as p:
        context = launch_stealth_persistent_context(p, str(user_data), headless=True)
        assert isinstance(context, BrowserContext)
        cookies = context.cookies()
        # Verify cookie was added cleanly
        cookie_names = [c["name"] for c in cookies]
        assert "test_cookie" in cookie_names
        context.close()
