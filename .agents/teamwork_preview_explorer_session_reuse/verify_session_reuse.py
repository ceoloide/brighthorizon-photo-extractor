import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# Add repository root to path
sys.path.insert(0, "/home/antigravity/GitHub/brighthorizon-photo-extractor")

from backend.database import TenantStorage
from backend.scraper_engine import ScraperJob

class TestSessionReuse(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.mock_tenant_storage = MagicMock(spec=TenantStorage)
        self.mock_tenant_storage.email = "test@example.com"
        self.mock_tenant_storage.user_data_dir = os.path.join(self.test_dir, "user_data")
        os.makedirs(self.mock_tenant_storage.user_data_dir, exist_ok=True)
        self.state_file = os.path.join(self.mock_tenant_storage.user_data_dir, "storage_state.json")

    def test_1_storage_state_file_loading_when_present(self):
        """Verify browser.new_context is called with storage_state when storage_state.json exists."""
        # Create dummy storage_state.json
        with open(self.state_file, "w") as f:
            f.write('{"cookies": [{"name": "session", "value": "123"}], "origins": []}')

        job = ScraperJob(self.mock_tenant_storage, "dummy_password", {})

        with patch("backend.scraper_engine.sync_playwright") as mock_playwright, \
             patch("backend.scraper_engine.ensure_xvfb_display") as mock_xvfb, \
             patch.object(job, "detect_page_state", return_value="authenticated"), \
             patch.object(job, "discover_children", return_value=[{"name": "Child1", "dependent_id": "dep1"}]), \
             patch.object(job, "extract_child_feed"):

            mock_p = MagicMock()
            mock_playwright.return_value.__enter__.return_value = mock_p
            mock_browser = MagicMock()
            mock_p.chromium.launch.return_value = mock_browser
            mock_context = MagicMock()
            mock_browser.new_context.return_value = mock_context
            mock_page = MagicMock()
            mock_context.new_page.return_value = mock_page

            job.run()

            # Verify new_context called with storage_state
            mock_browser.new_context.assert_called_once()
            _, kwargs = mock_browser.new_context.call_args
            self.assertIn("storage_state", kwargs)
            self.assertEqual(kwargs["storage_state"], self.state_file)
            print("✓ Test 1 Passed: browser.new_context received storage_state when file exists.")

    def test_2_storage_state_file_not_loaded_when_missing(self):
        """Verify browser.new_context is called without storage_state when storage_state.json is absent."""
        if os.path.exists(self.state_file):
            os.remove(self.state_file)

        job = ScraperJob(self.mock_tenant_storage, "dummy_password", {})

        with patch("backend.scraper_engine.sync_playwright") as mock_playwright, \
             patch("backend.scraper_engine.ensure_xvfb_display") as mock_xvfb, \
             patch.object(job, "detect_page_state", return_value="auth0_username"), \
             patch.object(job, "perform_login") as mock_perform_login, \
             patch.object(job, "discover_children", return_value=[{"name": "Child1", "dependent_id": "dep1"}]), \
             patch.object(job, "extract_child_feed"):

            mock_p = MagicMock()
            mock_playwright.return_value.__enter__.return_value = mock_p
            mock_browser = MagicMock()
            mock_p.chromium.launch.return_value = mock_browser
            mock_context = MagicMock()
            mock_browser.new_context.return_value = mock_context
            mock_page = MagicMock()
            mock_context.new_page.return_value = mock_page

            job.run()

            # Verify new_context called without storage_state
            mock_browser.new_context.assert_called_once()
            _, kwargs = mock_browser.new_context.call_args
            self.assertNotIn("storage_state", kwargs)
            mock_perform_login.assert_called_once()
            print("✓ Test 2 Passed: browser.new_context omits storage_state when file is missing, falling back to perform_login.")

    def test_3_login_step_bypass_when_authenticated(self):
        """Verify perform_login is completely bypassed if page state is 'authenticated'."""
        with open(self.state_file, "w") as f:
            f.write('{"cookies": [{"name": "session", "value": "123"}], "origins": []}')

        job = ScraperJob(self.mock_tenant_storage, "dummy_password", {})

        with patch("backend.scraper_engine.sync_playwright") as mock_playwright, \
             patch("backend.scraper_engine.ensure_xvfb_display"), \
             patch.object(job, "detect_page_state", return_value="authenticated"), \
             patch.object(job, "perform_login") as mock_perform_login, \
             patch.object(job, "discover_children", return_value=[{"name": "Child1", "dependent_id": "dep1"}]), \
             patch.object(job, "extract_child_feed"):

            mock_p = MagicMock()
            mock_playwright.return_value.__enter__.return_value = mock_p
            mock_browser = MagicMock()
            mock_p.chromium.launch.return_value = mock_browser
            mock_context = MagicMock()
            mock_browser.new_context.return_value = mock_context
            mock_page = MagicMock()
            mock_context.new_page.return_value = mock_page

            job.run()

            # perform_login should NOT be called
            mock_perform_login.assert_not_called()
            print("✓ Test 3 Passed: perform_login was successfully bypassed for authenticated session.")

    def test_4_login_triggered_when_session_expired(self):
        """Verify perform_login is triggered when page state is unauthenticated (e.g. expired session)."""
        with open(self.state_file, "w") as f:
            f.write('{"cookies": [{"name": "expired_session", "value": "xyz"}], "origins": []}')

        job = ScraperJob(self.mock_tenant_storage, "dummy_password", {})

        with patch("backend.scraper_engine.sync_playwright") as mock_playwright, \
             patch("backend.scraper_engine.ensure_xvfb_display"), \
             patch.object(job, "detect_page_state", return_value="auth0_username"), \
             patch.object(job, "perform_login") as mock_perform_login, \
             patch.object(job, "discover_children", return_value=[{"name": "Child1", "dependent_id": "dep1"}]), \
             patch.object(job, "extract_child_feed"):

            mock_p = MagicMock()
            mock_playwright.return_value.__enter__.return_value = mock_p
            mock_browser = MagicMock()
            mock_p.chromium.launch.return_value = mock_browser
            mock_context = MagicMock()
            mock_browser.new_context.return_value = mock_context
            mock_page = MagicMock()
            mock_context.new_page.return_value = mock_page

            job.run()

            # perform_login MUST be called
            mock_perform_login.assert_called_once()
            print("✓ Test 4 Passed: perform_login was triggered after detecting expired/unauthenticated session state.")

if __name__ == "__main__":
    unittest.main()
