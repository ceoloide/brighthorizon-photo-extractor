# Independent Verification Test Script for Victory Audit
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure backend can be imported
sys.path.insert(0, "/home/antigravity/GitHub/brighthorizon-photo-extractor")

from backend.database import TenantStorage
from backend.scraper_engine import ScraperJob
from backend.server import app, _active_jobs, cancel_extraction, extraction_status

class TestVictoryAuditRequirements(unittest.TestCase):
    def setUp(self):
        self.email = "victory_audit_user@example.com"
        self.storage = TenantStorage(self.email)
        self.storage.purge_all_data()
        _active_jobs.pop(self.storage.tenant_id, None)

    def tearDown(self):
        _active_jobs.pop(self.storage.tenant_id, None)
        self.storage.purge_all_data()

    def test_requirement_1_job_cancellation_responsiveness(self):
        """Req 1: Verify POST /api/extraction/cancel immediately closes active Playwright context and updates status to 'cancelled'."""
        job = ScraperJob(self.storage, "dummy_pass", {})
        job.status["state"] = "running"
        
        mock_page = MagicMock()
        mock_context = MagicMock()
        mock_page.context = mock_context
        job._active_page = mock_page

        _active_jobs[self.storage.tenant_id] = job

        # Execute cancellation
        result = cancel_extraction(tenant=self.storage)
        
        self.assertEqual(result["status"], "cancelled")
        self.assertTrue(job._cancelled)
        self.assertEqual(job.status["state"], "cancelled")
        self.assertIn("cancelled", job.status["current_step"].lower())
        self.assertTrue(job._mfa_event.is_set())
        self.assertTrue(job._step_event.is_set())
        self.assertIsNone(job._active_page)
        mock_context.close.assert_called_once()
        print("PASS: Requirement 1 - Job Cancellation Responsiveness verified!")

    def test_requirement_2_session_cookie_reuse(self):
        """Req 2: Verify ScraperJob.run() loads storage_state.json via browser.new_context(storage_state=...) and skips login when valid."""
        # Create a fake storage_state.json file
        state_file = os.path.join(self.storage.user_data_dir, "storage_state.json")
        os.makedirs(os.path.dirname(state_file), exist_ok=True)
        with open(state_file, "w") as f:
            f.write('{"cookies": [], "origins": []}')

        job = ScraperJob(self.storage, "dummy_pass", {})

        with patch("backend.scraper_engine.ensure_xvfb_display"), \
             patch("backend.scraper_engine.sync_playwright") as mock_playwright:
            
            mock_p = MagicMock()
            mock_playwright.return_value.__enter__.return_value = mock_p
            mock_browser = MagicMock()
            mock_p.chromium.launch.return_value = mock_browser
            mock_context = MagicMock()
            mock_browser.new_context.return_value = mock_context
            mock_page = MagicMock()
            mock_context.new_page.return_value = mock_page

            with patch.object(job, "detect_page_state", return_value="authenticated"), \
                 patch.object(job, "discover_children", return_value=[{"name": "Child1"}]), \
                 patch.object(job, "extract_child_feed") as mock_extract, \
                 patch.object(job, "perform_login") as mock_perform_login:
                
                job.run()
                
                # Check new_context call
                mock_browser.new_context.assert_called_once()
                call_kwargs = mock_browser.new_context.call_args[1]
                self.assertIn("storage_state", call_kwargs)
                self.assertEqual(call_kwargs["storage_state"], state_file)

                # Check perform_login was NOT called because detect_page_state returned "authenticated"
                mock_perform_login.assert_not_called()
                print("PASS: Requirement 2 - Session Cookie & LocalStorage Reuse verified!")

    def test_requirement_3_ui_header_branding_and_log_drawer(self):
        """Req 3: Verify header title is 'Bright Horizon Photo Extractor', Sync chip is removed, and console logs are collapsed by default."""
        dashboard_path = "/home/antigravity/GitHub/brighthorizon-photo-extractor/frontend/src/components/Dashboard.tsx"
        with open(dashboard_path, "r") as f:
            code = f.read()

        # Check 1: Header title
        self.assertIn("Bright Horizon Photo Extractor", code)
        
        # Check 2: Collapsed console logs by default
        self.assertIn("const [showLogs, setShowLogs] = useState<boolean>(false);", code)

        # Check 3: Header navbar contains no Sync chip
        header_start = code.find("<header")
        header_end = code.find("</header>")
        self.assertNotEqual(header_start, -1)
        self.assertNotEqual(header_end, -1)
        header_html = code[header_start:header_end]
        
        self.assertNotIn("Sync chip", header_html)
        self.assertNotIn("Sync Mode", header_html)
        self.assertNotIn("Syncing", header_html)
        print("PASS: Requirement 3 - UI Header Branding & Log Drawer verified!")

if __name__ == "__main__":
    unittest.main()
