"""
Tests for GDrive and MEGA cloud services.
"""

from unittest.mock import MagicMock, mock_open, patch

from app.db import models
from app.services.gdrive_service import get_valid_access_token, get_valid_credentials
from app.services.gdrive_service import list_files as gdrive_list
from app.services.mega_service import (
    _ensure_sessions_dir,
    get_mega_session,
    invalidate_session,
    login_to_mega,
)
from app.services.mega_service import list_files as mega_list

# -------------------------
# GDrive Service Tests
# -------------------------


@patch("app.services.gdrive_service.Credentials")
@patch("app.services.gdrive_service.Request")
def test_get_valid_credentials_refresh(mock_request, mock_creds, db):
    """Test refreshing Google Drive credentials."""
    _ = mock_request
    account = models.Account(
        user_id=1,
        provider="gdrive",
        email="t@t.com",
        access_token="old",
        refresh_token="refresh",
    )
    db.add(account)
    db.commit()
    db.refresh(account)

    mock_creds_instance = MagicMock()
    mock_creds.return_value = mock_creds_instance
    mock_creds_instance.expired = True
    mock_creds_instance.valid = False
    mock_creds_instance.token = "new_token"

    creds = get_valid_credentials(account, db)
    assert account.access_token == "new_token"
    assert creds == mock_creds_instance
    mock_creds_instance.refresh.assert_called_once()


@patch("app.services.gdrive_service.Credentials")
@patch("app.services.gdrive_service.Request")
def test_get_valid_access_token(mock_request, mock_creds, db):
    """Test fetching a valid access token for GDrive."""
    _ = mock_request
    account = models.Account(
        user_id=1,
        provider="gdrive",
        email="t@t.com",
        access_token="old",
        refresh_token="refresh",
    )
    db.add(account)
    db.commit()
    db.refresh(account)

    mock_creds_instance = MagicMock()
    mock_creds.return_value = mock_creds_instance
    mock_creds_instance.token = "new_token"

    token = get_valid_access_token(account, db)
    assert token == "new_token"
    assert account.access_token == "new_token"


@patch("app.services.gdrive_service.build")
@patch("app.services.gdrive_service.get_valid_credentials")
def test_gdrive_list_files_success(mock_get_creds, mock_build, db):
    """Test successful file listing from Google Drive."""
    _ = db
    account = models.Account(id=1, email="test@test.com")
    mock_get_creds.return_value = MagicMock()
    mock_service = mock_build.return_value
    mock_service.files.return_value.list.return_value.execute.return_value = {
        "files": [
            {"id": "1", "name": "f1", "mimeType": "application/vnd.google-apps.folder"},
            {"id": "2", "name": "f2", "mimeType": "image/jpeg", "size": "1024"},
        ]
    }

    files = gdrive_list(account, db, "root")
    assert len(files) == 2
    assert files[0]["type"] == "folder"
    assert files[1]["type"] == "file"
    assert files[1]["size"] == 1024


@patch("app.services.gdrive_service.build")
@patch("app.services.gdrive_service.get_valid_credentials")
def test_gdrive_list_files_folder(mock_get_creds, mock_build, db):
    """Test GDrive list_files with a specific folder ID."""
    _ = db
    account = models.Account(id=1, email="test@test.com")
    mock_get_creds.return_value = MagicMock()
    mock_service = mock_build.return_value
    mock_service.files.return_value.list.return_value.execute.return_value = {
        "files": []
    }

    files = gdrive_list(account, db, "some_folder_id")
    assert not files
    mock_service.files.return_value.list.assert_called_with(
        q="'some_folder_id' in parents and trashed=false",
        pageSize=50,
        fields="files(id, name, mimeType, size)",
    )


def test_gdrive_list_files_exception(db):
    """Test exception handling in GDrive file listing."""
    account = models.Account(id=1, email="test@test.com")
    with patch("app.services.gdrive_service.build") as mock_build:
        mock_service = mock_build.return_value
        mock_service.files.return_value.list.return_value.execute.side_effect = (
            Exception("error")
        )
        assert not gdrive_list(account, db, "root")


# -------------------------
# Mega Service Tests
# -------------------------


@patch("app.services.mega_service.Mega")
@patch("app.services.mega_service.time.monotonic")
@patch("app.services.mega_service._last_login_attempt", {})
def test_login_to_mega_throttled(mock_time, mock_mega_class):
    """Test MEGA login throttling."""
    mock_time.return_value = 100.0
    from app.services.mega_service import _last_login_attempt

    _last_login_attempt["throttled@test.com"] = 90.0  # Last attempt 10s ago

    m = login_to_mega("throttled@test.com", "pass")
    assert m is None
    mock_mega_class.assert_not_called()


@patch("app.services.mega_service._MEGA_SESSIONS", {})
@patch("app.services.mega_service._load_session")
@patch("app.services.mega_service.Mega")
@patch("app.services.mega_service._last_login_attempt", {})
def test_get_mega_session_logic(mock_mega_class, mock_load):
    """Test logic for retrieving MEGA session (cache, disk, login)."""
    # Case 1: Load from disk
    mock_load.return_value = MagicMock()
    m1 = get_mega_session("disk@test.com", "pass")
    assert m1 is not None

    # Case 2: Fresh login
    mock_load.return_value = None
    mock_mega_instance = mock_mega_class.return_value
    mock_mega_instance.login.return_value = MagicMock()

    m2 = get_mega_session("fresh@test.com", "pass")
    assert m2 is not None

    # Case 3: In-memory reuse
    m3 = get_mega_session("fresh@test.com", "pass")
    assert m3 == m2


def test_get_mega_session_invalid_creds():
    """Test MEGA session retrieval with missing credentials."""
    assert get_mega_session(None, "pass") is None
    assert get_mega_session("user", None) is None


def test_mega_list_files_empty():
    """Test listing files from an empty MEGA account."""
    m = MagicMock()
    m.get_files.return_value = {}
    assert not mega_list(m, "root")


def test_mega_list_files_exception():
    """Test exception handling in MEGA file listing."""
    m = MagicMock()
    m.get_files.side_effect = Exception("error")
    assert not mega_list(m, "root")


def test_ensure_sessions_dir():
    """Test creation of MEGA sessions directory."""
    with patch("app.services.mega_service.os.makedirs") as mock_makedirs:
        path = _ensure_sessions_dir()
        assert "mega_sessions" in path
        mock_makedirs.assert_called()


@patch("app.services.mega_service.os.path.exists")
@patch("app.services.mega_service.pickle.load")
@patch("builtins.open", new_callable=mock_open)
def test_load_session_valid(mock_file, mock_pickle_load, mock_exists):
    """Test loading a valid MEGA session from disk."""
    _ = mock_file
    mock_exists.return_value = True
    mock_session = MagicMock()
    mock_pickle_load.return_value = mock_session

    from app.services.mega_service import _load_session

    m = _load_session("test@test.com")
    assert m == mock_session
    mock_session.get_quota.assert_called_once()


def test_load_session_not_found():
    """Test MEGA session loading when file doesn't exist."""
    from app.services.mega_service import _load_session

    with patch("app.services.mega_service.os.path.exists", return_value=False):
        assert _load_session("notfound@test.com") is None


@patch("app.services.mega_service.os.path.exists")
@patch("builtins.open", side_effect=Exception("load error"))
def test_load_session_exception(mock_file, mock_exists):
    """Test exception handling during MEGA session loading."""
    _ = mock_file
    mock_exists.return_value = True
    from app.services.mega_service import _load_session

    assert _load_session("test@test.com") is None


@patch("app.services.mega_service.Mega")
def test_login_to_mega_json_error(mock_mega_class):
    """Test MEGA login with JSON decoding error."""
    mock_mega = mock_mega_class.return_value
    import json

    mock_mega.login.side_effect = json.JSONDecodeError("msg", "doc", 0)

    m = login_to_mega("test@test.com", "pass")
    assert m is None


@patch("app.services.mega_service.Mega")
@patch("builtins.open", new_callable=mock_open)
@patch("app.services.mega_service.pickle.dump")
@patch("app.services.mega_service._last_login_attempt", {})
def test_login_to_mega_success(mock_dump, mock_file, mock_mega_class):
    """Test successful MEGA login and session saving."""
    _ = mock_file
    mock_mega_instance = mock_mega_class.return_value
    mock_mega_instance.login.return_value = MagicMock()

    m = login_to_mega("test_success@test.com", "pass")
    assert m is not None
    mock_dump.assert_called_once()


@patch("app.services.mega_service.Mega")
@patch("app.services.mega_service._last_login_attempt", {})
def test_login_to_mega_unexpected_error(mock_mega_class):
    """Test MEGA login with an unexpected error."""
    mock_mega_instance = mock_mega_class.return_value
    mock_mega_instance.login.side_effect = Exception("Unexpected")

    m = login_to_mega("error@test.com", "pass")
    assert m is None


def test_login_to_mega_missing_creds():
    """Test MEGA login with missing credentials."""
    assert login_to_mega(None, "pass") is None
    assert login_to_mega("user", None) is None


@patch("app.services.mega_service.os.path.exists")
@patch("app.services.mega_service.os.remove")
def test_invalidate_session_error(mock_remove, mock_exists):
    """Test session invalidation error handling."""
    mock_exists.return_value = True
    mock_remove.side_effect = OSError("error")
    invalidate_session("test@test.com")  # Should not raise


def test_mega_list_files_logic():
    """Test internal logic for parsing MEGA file lists."""
    m = MagicMock()
    m.get_files.return_value = {
        "root_h": {"t": 2, "p": None},
        "f1": {"t": 0, "p": "root_h", "a": {"n": "file1"}, "s": 100},
        "d1": {"t": 1, "p": "root_h", "a": {"n": "dir1"}},
    }

    files = mega_list(m, "root")
    assert len(files) == 2
    assert any(f["name"] == "file1" and f["type"] == "file" for f in files)
    assert any(f["name"] == "dir1" and f["type"] == "folder" for f in files)


def test_get_mega_download_url():
    """Test generation of MEGA download URLs."""
    from app.services.mega_service import get_mega_download_url

    m = MagicMock()
    m.get_files.return_value = {"file123": {}}
    m.get_link.return_value = "http://mega.nz/file123"

    url = get_mega_download_url(m, "file123")
    assert url == "http://mega.nz/file123"

    # Not found case
    assert get_mega_download_url(m, "notfound") is None

    # Exception case
    m.get_files.side_effect = Exception("error")
    assert get_mega_download_url(m, "file123") is None


def test_mega_list_files_navigation():
    """Test folder navigation in MEGA file lists."""
    m = MagicMock()
    m.get_files.return_value = {
        "folder1": {"t": 1, "p": "root_h", "a": {"n": "folder1"}},
        "file2": {"t": 0, "p": "folder1", "a": {"n": "file2"}, "s": 200},
        "skip1": {"t": 2, "p": "folder1", "a": {"n": "skip1"}},  # Type 2 skipped
        "wrong_parent": {"t": 0, "p": "other", "a": {"n": "wrong"}, "s": 300},
    }
    # List specific folder
    files = mega_list(m, "folder1")
    assert len(files) == 1
    assert files[0]["name"] == "file2"


@patch("app.services.gdrive_service.build")
@patch("app.services.gdrive_service.get_valid_credentials")
def test_gdrive_list_files_empty(mock_get_creds, mock_build, db):
    """Test listing files from an empty Google Drive account."""
    _ = db
    account = models.Account(id=1, email="test@test.com")
    mock_get_creds.return_value = MagicMock()
    mock_service = mock_build.return_value
    mock_service.files.return_value.list.return_value.execute.return_value = {}

    assert not gdrive_list(account, db, "root")


def test_save_session_exception():
    """Test exception handling during MEGA session saving."""
    from app.services.mega_service import _save_session

    m = MagicMock()
    with patch("builtins.open", side_effect=OSError("perm error")):
        _save_session("test@test.com", m)  # Should not raise
