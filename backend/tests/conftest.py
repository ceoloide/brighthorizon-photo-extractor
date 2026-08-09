import os
import pytest
from unittest.mock import patch

@pytest.fixture(autouse=True)
def isolate_test_data_dir(tmp_path, monkeypatch):
    """
    Autouse fixture that isolates all backend security and database storage operations
    to a temporary directory (`tmp_path`) for every unit test run.
    Ensures tests never modify or create tenant data in standard production/dev host paths.
    """
    temp_data_dir = str(tmp_path / "data")
    os.makedirs(temp_data_dir, exist_ok=True)
    
    monkeypatch.setenv("DATA_DIR", temp_data_dir)
    
    with patch("backend.security.DATA_DIR", temp_data_dir), \
         patch("backend.database.DATA_DIR", temp_data_dir):
        yield temp_data_dir
