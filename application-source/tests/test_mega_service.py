"""Tests for the MEGA cloud storage service."""
from unittest.mock import MagicMock, patch

import pytest

from app.services.mega_service import (
    _session_file,
    get_mega_session,
    invalidate_session,
    list_files,
)


@pytest.fixture
def mock_mega():
    """Fixture for a mock MEGA client instance."""
    with patch("app.services.mega_service.Mega") as mock:
        yield mock


@pytest.fixture
def mock_settings():
    """Fixture for mock settings with MEGA session directory."""
    with patch("app.services.mega_service.settings") as mock:
        mock.MEGA_SESSION_DIR = "/tmp/mega_sessions"
        yield mock


@pytest.mark.usefixtures("mock_settings")
def test_session_file_path():
    """Test the generation of session file paths."""
    email = "test@example.com"
    path = _session_file(email)
    assert "/tmp/mega_sessions" in path
    assert path.endswith(".pickle")


@pytest.mark.usefixtures("mock_settings")
def test_get_mega_session_caching(mock_mega):
    """Test that MEGA sessions are correctly cached in memory and on disk."""
    email = "test@example.com"
    password = "password"

    # Mock memory cache empty
    with patch("app.services.mega_service._MEGA_SESSIONS", {}):
        # Mock disk cache empty
        with patch("os.path.exists", return_value=False):
            # Mock successful login
            mock_instance = mock_mega.return_value
            mock_session = MagicMock()
            mock_instance.login.return_value = mock_session

            # 1. First call - should login
            session1 = get_mega_session(email, password)
            assert session1 == mock_session
            mock_instance.login.assert_called_once_with(email, password)

            # 2. Second call - should use memory cache
            mock_instance.login.reset_mock()
            session2 = get_mega_session(email, password)
            assert session2 == mock_session
            mock_instance.login.assert_not_called()


@pytest.mark.usefixtures("mock_settings")
def test_invalidate_session():
    """Test that invalidating a session removes it from cache and disk."""
    email = "test@example.com"
    path = _session_file(email)

    with patch("app.services.mega_service._MEGA_SESSIONS", {email: "some_session"}):
        with patch("os.path.exists", return_value=True):
            with patch("os.remove") as mock_remove:
                invalidate_session(email)
                mock_remove.assert_called_once_with(path)


def test_list_files_mapping():
    """Test mapping MEGA file metadata to the internal file format."""
    mock_session = MagicMock()
    mock_session.get_files.return_value = {
        "handle1": {
            "h": "handle1",
            "p": "root_handle",
            "t": 0,  # file
            "a": {"n": "video.mp4"},
            "s": 1024,
        },
        "handle2": {
            "h": "handle2",
            "p": "root_handle",
            "t": 1,  # folder
            "a": {"n": "Documents"},
            "s": 0,
        },
    }

    # Mock root handle identification
    # In list_files, it looks for t=2 for root handle
    mock_session.get_files.return_value["root_handle"] = {"t": 2}

    files = list_files(mock_session, folder_id="root")

    assert len(files) == 2
    assert files[0]["name"] == "video.mp4"
    assert files[0]["type"] == "file"
    assert files[1]["name"] == "Documents"
    assert files[1]["type"] == "folder"
