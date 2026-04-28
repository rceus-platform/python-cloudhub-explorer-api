"""Tests for GDrive and MEGA cloud services."""

import json
from unittest.mock import MagicMock, mock_open, patch

import pytest

from app.db import models
from app.services.gdrive_service import get_valid_access_token, get_valid_credentials
from app.services.gdrive_service import list_files as gdrive_list
from app.services.mega_service import (
    _ensure_sessions_dir,
    _load_session,
    get_mega_session,
    invalidate_session,
    login_to_mega,
)
from app.services.mega_service import list_files as mega_list


@patch("app.services.gdrive_service.Credentials")
@patch("app.services.gdrive_service.Request")
def test_get_valid_credentials_refresh(mock_request, mock_creds, db):
    """Test refreshing Google Drive credentials."""

    _ = mock_request
    account = models.Account(
        user_id=1,
        provider="gdrive",
        access_token="old_access",
        refresh_token="valid_refresh",
    )
    db.add(account)
    db.commit()

    mock_instance = mock_creds.return_value
    mock_instance.expired = True
    mock_instance.token = "new_access_token"

    creds = get_valid_credentials(account, db)
    assert creds.token == "new_access_token"
    assert account.access_token == "new_access_token"


@patch("app.services.gdrive_service.Credentials")
@patch("app.services.gdrive_service.Request")
def test_get_valid_access_token(mock_request, mock_creds, db):
    """Test fetching a valid access token for GDrive."""

    _ = mock_request
    mock_instance = mock_creds.return_value
    mock_instance.expired = False
    mock_instance.token = "test_token"

    account = models.Account(
        id=1, provider="gdrive", access_token="t", refresh_token="r"
    )
    token = get_valid_access_token(account, db)
    assert token == "test_token"


@patch("app.services.gdrive_service.build")
@patch("app.services.gdrive_service.get_valid_credentials")
def test_gdrive_list_files_success(mock_get_creds, mock_build, db):
    """Test successful file listing from Google Drive."""

    _ = mock_get_creds
    account = models.Account(id=1, email="test@test.com")
    mock_service = mock_build.return_value
    mock_service.files.return_value.list.return_value.execute.return_value = {
        "files": [{"id": "1", "name": "file.txt", "mimeType": "text/plain"}]
    }

    files = gdrive_list(account, db, "root")
    assert len(files) == 1
    assert files[0]["name"] == "file.txt"
    assert files[0]["provider"] == "gdrive"


@patch("app.services.gdrive_service.build")
@patch("app.services.gdrive_service.get_valid_credentials")
def test_gdrive_list_files_folder(mock_get_creds, mock_build, db):
    """Test GDrive list_files with a specific folder ID."""

    _ = mock_get_creds
    account = models.Account(id=1, email="test@test.com")
    mock_service = mock_build.return_value
    mock_service.files.return_value.list.return_value.execute.return_value = {
        "files": []
    }

    gdrive_list(account, db, "folder123")
    assert mock_service.files.return_value.list.called


@patch("app.services.gdrive_service.get_valid_credentials")
def test_gdrive_list_files_exception(mock_get_creds, db):
    """Test exception handling in GDrive file listing."""

    _ = mock_get_creds
    account = models.Account(id=1, email="test@test.com")
    with patch("app.services.gdrive_service.build") as mock_build:
        mock_service = mock_build.return_value
        mock_service.files.return_value.list.return_value.execute.side_effect = (
            Exception("error")
        )
        with pytest.raises(Exception):
            gdrive_list(account, db, "root")


@patch("app.services.mega_service._last_login_attempt", {"test@test.com": 9999999999})
def test_login_to_mega_throttled():
    """Test MEGA login throttling."""

    assert login_to_mega("test@test.com", "pass") is None


@patch("app.services.mega_service._load_session")
@patch("app.services.mega_service.login_to_mega")
def test_get_mega_session_logic(mock_login, mock_load):
    """Test logic for retrieving MEGA session (cache, disk, login)."""

    # 1. From disk
    mock_load.return_value = "session_obj"
    assert get_mega_session("u@t.com", "p") == "session_obj"

    # 2. From login
    mock_load.return_value = None
    mock_login.return_value = "new_session"
    assert get_mega_session("u2@t.com", "p") == "new_session"


def test_get_mega_session_no_creds():
    """Test MEGA session retrieval with missing credentials."""

    assert get_mega_session(None, None) is None


def test_mega_list_files_none():
    """Test listing files from an empty MEGA account."""

    assert not mega_list(None, "root")


def test_mega_list_files_exception():
    """Test exception handling in MEGA file listing."""

    mock_session = MagicMock()
    mock_session.get_files.side_effect = Exception("fail")
    assert not mega_list(mock_session, "root")


@patch("app.services.mega_service.os.makedirs")
def test_ensure_sessions_dir(mock_makedirs):
    """Test creation of MEGA sessions directory."""

    _ensure_sessions_dir()
    mock_makedirs.assert_called()


@patch("app.services.mega_service.os.path.exists")
@patch("app.services.mega_service.hmac.compare_digest")
def test_load_session_valid(mock_compare, mock_exists):
    """Test loading a valid MEGA session from disk."""

    mock_exists.return_value = True
    mock_compare.return_value = True
    with patch("app.services.mega_service.open", mock_open(read_data=b"dummy")):
        with patch("app.services.mega_service.pickle.loads") as mock_pickle_loads:
            mock_session = MagicMock()
            mock_pickle_loads.return_value = mock_session
            assert _load_session("test@test.com") == mock_session


@patch("app.services.mega_service.os.path.exists")
def test_load_session_not_found(mock_exists):
    """Test MEGA session loading when file doesn't exist."""

    mock_exists.return_value = False
    assert _load_session("test@test.com") is None


@patch("app.services.mega_service.os.path.exists")
@patch("app.services.mega_service.open", side_effect=Exception("error"))
def test_load_session_exception(mock_file, mock_exists):
    """Test exception handling during MEGA session loading."""

    _ = mock_file
    mock_exists.return_value = True
    assert _load_session("test@test.com") is None


@patch("app.services.mega_service._last_login_attempt", {})
@patch("app.services.mega_service.Mega")
def test_login_to_mega_json_error(mock_mega_class):
    """Test MEGA login with JSON decoding error."""

    mock_mega = mock_mega_class.return_value
    mock_mega.login.side_effect = json.JSONDecodeError("msg", "doc", 0)

    m = login_to_mega("test@test.com", "pass")
    assert m is None


@patch("app.services.mega_service._last_login_attempt", {})
@patch("app.services.mega_service.Mega")
@patch("app.services.mega_service.open", new_callable=mock_open)
def test_login_to_mega_success(mock_file, mock_mega_class):
    """Test successful MEGA login and session saving."""

    mock_mega = mock_mega_class.return_value
    mock_mega.login.return_value = mock_mega
    with patch("app.services.mega_service.pickle.dumps") as mock_pickle_dumps:
        mock_pickle_dumps.return_value = b"pickled_data"
        m = login_to_mega("test@test.com", "pass")
        assert m == mock_mega
        assert mock_file.call_count == 2


@patch("app.services.mega_service._last_login_attempt", {})
@patch("app.services.mega_service.Mega")
def test_login_to_mega_exception(mock_mega_class):
    """Test MEGA login with an unexpected error."""

    mock_mega = mock_mega_class.return_value
    mock_mega.login.side_effect = Exception("fail")
    assert login_to_mega("test@test.com", "pass") is None


def test_login_to_mega_no_creds():
    """Test MEGA login with missing credentials."""

    assert login_to_mega(None, None) is None


@patch("app.services.mega_service.os.remove")
def test_invalidate_session_error(mock_remove):
    """Test session invalidation error handling."""

    mock_remove.side_effect = Exception("fail")
    invalidate_session("test@test.com")
