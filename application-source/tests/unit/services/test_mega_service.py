"""Tests for the MEGA cloud storage service."""

import time
from unittest.mock import MagicMock, patch

import pytest

from app.services.mega_service import (
    _session_file,
    get_mega_session,
    get_storage_info,
    invalidate_session,
    list_files,
    login_to_mega,
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
def test_login_throttling():
    """Test that MEGA logins are throttled after a recent attempt."""

    email = "throttle@example.com"
    password = "pass"

    with patch("app.services.mega_service._last_login_attempt", {email: time.monotonic()}):
        session = login_to_mega(email, password)
        assert session is None


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
    mock_session.get_files.return_value["root_handle"] = {"t": 2}

    files = list_files(mock_session, "test@example.com", folder_id="root")

    assert len(files) == 2
    assert files[0]["name"] == "video.mp4"
    assert files[0]["type"] == "file"
    assert files[1]["name"] == "Documents"
    assert files[1]["type"] == "folder"


def test_list_files_error():
    """Test listing files when the MEGA API returns an error."""

    mock_session = MagicMock()
    mock_session.get_files.side_effect = Exception("API error")
    files = list_files(mock_session, "test@example.com")
    assert not files


def test_get_storage_info():
    """Test retrieving storage quota and usage information from MEGA."""

    mock_session = MagicMock()
    mock_session.email = "test@example.com"
    mock_session.get_storage_space.return_value = {
        "total": 50 * 1024 * 1024 * 1024,
        "used": 10 * 1024 * 1024 * 1024,
    }

    info = get_storage_info(mock_session)
    assert info["storage_total"] == 50 * 1024 * 1024 * 1024
    assert info["storage_used"] == 10 * 1024 * 1024 * 1024


def test_get_storage_info_fallback():
    """Test retrieving storage info using the quota fallback when get_storage_space fails."""

    mock_session = MagicMock()
    mock_session.email = "test@example.com"
    mock_session.get_storage_space.side_effect = Exception("failed")
    mock_session.get_quota.return_value = 50 * 1024  # MB

    info = get_storage_info(mock_session)
    assert info["storage_total"] == 53687091200


@pytest.mark.usefixtures("mock_settings")
def test_get_mega_session_load_disk():
    """Test loading MEGA session from disk cache."""
    email = "disk@example.com"
    with patch("app.services.mega_service._MEGA_SESSIONS", {}):
        with patch("os.path.exists", return_value=True):
            from unittest.mock import mock_open

            with patch("builtins.open", mock_open()):
                with patch("pickle.load") as mock_load:
                    mock_session = MagicMock()
                    mock_load.return_value = mock_session
                    # 1. Success load
                    session = get_mega_session(email, "pass")
                    assert session == mock_session

                    # 2. Failure load (Exception)
                    mock_load.side_effect = Exception("Corrupt")
                    with patch("app.services.mega_service.invalidate_session") as mock_inv:
                        # We need to reset memory cache for this part
                        with patch("app.services.mega_service._MEGA_SESSIONS", {}):
                            with patch(
                                "app.services.mega_service.login_to_mega", return_value=None
                            ):
                                session = get_mega_session(email, "pass")
                                assert session is None
                                mock_inv.assert_called_once_with(email)


def test_get_storage_info_numeric():
    """Test get_storage_info with numeric quota response."""
    mock_session = MagicMock()
    mock_session.email = "test@email.com"
    mock_session.get_storage_space.side_effect = Exception()
    mock_session.get_quota.return_value = 1000  # 1000 MB
    info = get_storage_info(mock_session)
    assert info["storage_total"] == 1000 * 1024 * 1024


def test_get_storage_info_error():
    """Test get_storage_info with total API failure."""
    mock_session = MagicMock()
    mock_session.get_storage_space.side_effect = Exception()
    mock_session.get_quota.side_effect = Exception()
    info = get_storage_info(mock_session)
    assert info["storage_total"] == 0


def test_list_files_no_files():
    """Test list_files with empty response."""
    mock_session = MagicMock()
    mock_session.get_files.return_value = None
    files = list_files(mock_session, "test@example.com")
    assert not files


def test_login_to_mega_no_creds():
    """Test login_to_mega with missing credentials."""
    assert login_to_mega(None, "pass") is None
    assert login_to_mega("email", None) is None


@pytest.mark.usefixtures("mock_settings")
def test_save_session_error():
    """Test save_session handling write errors."""
    with patch("builtins.open", side_effect=IOError("Write denied")):
        from app.services.mega_service import _save_session

        _save_session("test@email.com", MagicMock())
        # Should not raise exception
