"""Tests for the Files API router."""

import json
from unittest.mock import MagicMock, patch
from app.db import models


@patch("app.api.routes.files.gdrive_list")
@patch("app.api.routes.files.mega_list")
@patch("app.api.routes.files.get_mega_session")
def test_list_files_root(
    mock_mega_session,
    mock_mega_list,
    mock_gdrive_list,
    authenticated_client,
    mock_accounts,
):
    """Test listing files from root directory."""

    _ = mock_accounts
    mock_gdrive_list.return_value = [
        {"id": "g1", "name": "f1", "type": "file", "provider": "gdrive"}
    ]
    mock_mega_list.return_value = [
        {"id": "m1", "name": "f2", "type": "file", "provider": "mega"}
    ]
    mock_mega_session.return_value = MagicMock()
    response = authenticated_client.get("/files/?folder_id=root")
    assert response.status_code == 200
    assert len(response.json()["files"]) == 2


@patch("app.api.routes.files.requests.get")
@patch("app.api.routes.files.get_valid_access_token")
def test_stream_gdrive(
    mock_get_token, mock_requests_get, authenticated_client, mock_accounts
):
    """Test streaming a file from Google Drive."""

    _ = mock_accounts
    mock_get_token.return_value = "valid_token"
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Type": "video/mp4"}
    mock_response.iter_content.return_value = [b"chunk"]
    mock_requests_get.return_value = mock_response
    response = authenticated_client.get(
        "/files/stream?provider=gdrive&file_id=123&_file_name=v.mp4&account_id=1"
    )
    assert response.status_code == 200


@patch("app.api.routes.files.requests.get")
@patch("app.api.routes.files.get_mega_session")
def test_stream_mega(
    mock_mega_session, mock_requests_get, authenticated_client, mock_accounts
):
    """Test streaming a file from MEGA."""

    _ = mock_accounts
    mock_mega_session.return_value = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Type": "video/mp4"}
    mock_response.iter_content.return_value = [b"chunk"]
    mock_requests_get.return_value = mock_response
    response = authenticated_client.get(
        "/files/stream?provider=mega&file_id=m123&_file_name=v.mp4&account_id=2"
    )
    assert response.status_code == 200


def test_list_files_invalid_folder_id(authenticated_client):
    """Test listing files with an invalid folder ID format."""

    response = authenticated_client.get("/files/?folder_id=not_json")
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid folder_id format"


@patch("app.api.routes.files.get_mega_session")
@patch("app.api.routes.files.settings")
def test_list_files_mega_env_fail(
    mock_settings, mock_mega_session, authenticated_client
):
    """Test failure of environment-configured MEGA login."""

    mock_settings.MEGA_USERNAME = "env@test.com"
    mock_settings.MEGA_PASSWORD = "pass"
    mock_mega_session.side_effect = Exception("Fail")
    response = authenticated_client.get("/files/?folder_id=root")
    assert response.status_code == 200


@patch("app.api.routes.files.get_mega_session")
def test_list_files_mega_session_none(
    mock_mega_session, authenticated_client, mock_accounts
):
    """Test behavior when MEGA session cannot be established."""

    _ = mock_accounts
    mock_mega_session.return_value = None
    response = authenticated_client.get("/files/?folder_id=root")
    assert response.status_code == 200


@patch("app.api.routes.files.gdrive_list")
def test_list_files_unknown_provider(
    mock_gdrive_list, authenticated_client, db, test_user
):
    """Test listing files when an account has an unknown provider."""

    _ = mock_gdrive_list
    acc = models.Account(
        user_id=test_user.id, provider="unknown", access_token="t", email="u@t.com"
    )
    db.add(acc)
    db.commit()
    response = authenticated_client.get("/files/?folder_id=root")
    assert response.status_code == 200


@patch("app.api.routes.files.get_mega_session")
@patch("app.api.routes.files.mega_list")
def test_list_files_folder_mega_exception(
    mock_mega_list, mock_mega_session, authenticated_client, mock_accounts
):
    """Test exception handling during MEGA folder listing."""

    _ = mock_accounts
    fid = json.dumps({"mega": "mfolder"})
    mock_mega_session.return_value = MagicMock()
    mock_mega_list.side_effect = Exception("Fail")
    response = authenticated_client.get(f"/files/?folder_id={fid}")
    assert response.status_code == 200


@patch("app.api.routes.files.requests.get")
@patch("app.api.routes.files.get_mega_session")
def test_stream_mega_range_header(
    mock_mega_session, mock_requests_get, authenticated_client, mock_accounts
):
    """Test streaming from MEGA with a Range header."""

    _ = mock_accounts
    mock_response = MagicMock()
    mock_response.status_code = 206
    mock_response.headers = {
        "Content-Type": "video/mp4",
        "Content-Range": "bytes 0-4/10",
    }
    mock_response.iter_content.return_value = [b"chunk"]
    mock_requests_get.return_value = mock_response
    mock_mega_session.return_value = MagicMock()
    headers = {"Range": "bytes=0-4"}
    response = authenticated_client.get(
        "/files/stream?provider=mega&file_id=m123&_file_name=v.mp4&account_id=2",
        headers=headers,
    )
    assert response.status_code == 206


@patch("app.api.routes.files.requests.get")
@patch("app.api.routes.files.settings")
def test_stream_mega_env_config(mock_settings, mock_requests_get, client):
    """Test streaming from MEGA using environment-configured credentials."""

    mock_settings.MEGA_USERNAME = "env@test.com"
    mock_settings.MEGA_PASSWORD = "pass"
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Type": "video/mp4"}
    mock_response.iter_content.return_value = [b"chunk"]
    mock_requests_get.return_value = mock_response
    response = client.get("/files/stream?provider=mega&file_id=env123&_file_name=v.mp4")
    assert response.status_code == 200


def test_stream_unsupported_provider(authenticated_client):
    """Test streaming from an unsupported provider."""

    response = authenticated_client.get(
        "/files/stream?provider=dropbox&file_id=123&_file_name=v.mp4"
    )
    assert response.status_code == 400


@patch("app.api.routes.files.settings")
def test_stream_no_account_no_env(mock_settings, authenticated_client):
    """Test streaming when no account or environment credentials are available."""

    mock_settings.MEGA_USERNAME = None
    mock_settings.MEGA_PASSWORD = None
    response = authenticated_client.get(
        "/files/stream?provider=mega&file_id=123&_file_name=v.mp4&account_id=999"
    )
    assert response.status_code == 404
    assert "No linked mega account found" in response.json()["detail"]


@patch("app.api.routes.files.get_mega_session")
@patch("app.api.routes.files.mega_list")
@patch("app.api.routes.files.settings")
def test_list_files_mega_env_success(
    mock_settings, mock_mega_list, mock_mega_session, authenticated_client
):
    """Test successful listing from environment-configured MEGA account."""

    mock_settings.MEGA_USERNAME = "env@test.com"
    mock_settings.MEGA_PASSWORD = "pass"
    mock_mega_session.return_value = MagicMock()
    mock_mega_list.return_value = [
        {"id": "m1", "name": "f1", "type": "file", "provider": "mega"}
    ]
    response = authenticated_client.get("/files/?folder_id=root")
    assert response.status_code == 200
    assert any(f["name"] == "f1" for f in response.json()["files"])


@patch("app.api.routes.files.gdrive_list")
@patch("app.api.routes.files.mega_list")
@patch("app.api.routes.files.get_mega_session")
def test_list_files_folder_navigation_all(
    mock_mega_session,
    mock_mega_list,
    mock_gdrive_list,
    authenticated_client,
    mock_accounts,
):
    """Test complex folder navigation with multiple providers."""

    _ = mock_accounts
    fid = json.dumps({"gdrive": "gf", "mega": "mf", "unknown": "uf"})
    mock_mega_session.return_value = MagicMock()
    mock_mega_list.return_value = [
        {"id": "m1", "name": "f1", "type": "file", "provider": "mega"}
    ]
    mock_gdrive_list.return_value = [
        {"id": "g1", "name": "f2", "type": "file", "provider": "gdrive"}
    ]
    response = authenticated_client.get(f"/files/?folder_id={fid}")
    assert response.status_code == 200


@patch("app.api.routes.files.get_mega_session")
def test_list_files_folder_mega_none(
    mock_mega_session, authenticated_client, mock_accounts
):
    """Test behavior when MEGA session fails during folder navigation."""

    _ = mock_accounts
    fid = json.dumps({"mega": "mf"})
    mock_mega_session.return_value = None
    response = authenticated_client.get(f"/files/?folder_id={fid}")
    assert response.status_code == 200
