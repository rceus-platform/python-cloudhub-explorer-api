"""Tests for the Google Drive service."""

from unittest.mock import MagicMock, patch

import pytest

from app.db import models
from app.services import gdrive_service


@pytest.fixture
def mock_account():
    """Fixture to provide a mock Google Drive account."""

    return models.Account(
        email="test@gmail.com",
        access_token="old_token",
        refresh_token="refresh_token",
        provider="gdrive",
    )


@patch("app.services.gdrive_service.Credentials")
def test_get_valid_credentials_no_refresh(mock_creds_class, mock_account, mock_db):
    """Test getting valid credentials when they are not expired."""

    mock_creds = MagicMock()
    mock_creds.expired = False
    mock_creds.valid = True
    mock_creds_class.return_value = mock_creds

    creds = gdrive_service.get_valid_credentials(mock_account, mock_db)

    assert creds == mock_creds
    mock_creds.refresh.assert_not_called()


@patch("app.services.gdrive_service.Credentials")
@patch("google.auth.transport.requests.Request")
def test_get_valid_credentials_with_refresh(_mock_request, mock_creds_class, mock_account, mock_db):
    """Test getting valid credentials when they require a refresh."""

    mock_creds = MagicMock()
    mock_creds.expired = True
    mock_creds.valid = False
    mock_creds.token = "new_token"
    mock_creds_class.return_value = mock_creds

    creds = gdrive_service.get_valid_credentials(mock_account, mock_db)

    assert creds == mock_creds
    mock_creds.refresh.assert_called_once()
    assert mock_account.access_token == "new_token"
    mock_db.commit.assert_called_once()


@patch("app.services.gdrive_service.Credentials")
def test_get_valid_credentials_refresh_fail(mock_creds_class, mock_account, mock_db):
    """Test getting valid credentials when the refresh operation fails."""

    mock_creds = MagicMock()
    mock_creds.expired = True
    mock_creds.refresh.side_effect = Exception("refresh failed")
    mock_creds_class.return_value = mock_creds

    creds = gdrive_service.get_valid_credentials(mock_account, mock_db)
    assert creds is None


@patch("app.services.gdrive_service.get_drive_service")
@patch("app.services.gdrive_service.get_valid_credentials")
def test_list_files_success(mock_get_creds, mock_get_service, mock_account, mock_db):
    """Test successfully listing files from Google Drive."""

    mock_get_creds.return_value = MagicMock()
    mock_service = MagicMock()
    mock_get_service.return_value = mock_service

    mock_service.files.return_value.list.return_value.execute.return_value = {
        "files": [
            {"id": "f1", "name": "file1.mp4", "mimeType": "video/mp4", "size": "100"},
            {
                "id": "f2",
                "name": "folder1",
                "mimeType": "application/vnd.google-apps.folder",
            },
        ]
    }

    files = gdrive_service.list_files(mock_account, mock_db, "root")

    assert len(files) == 2
    assert files[0]["name"] == "file1.mp4"
    assert files[0]["type"] == "file"
    assert files[1]["type"] == "folder"
    assert files[0]["id"] == "test@gmail.com:f1"


@patch("app.services.gdrive_service.get_drive_service")
@patch("app.services.gdrive_service.get_valid_credentials")
def test_list_files_api_error(mock_get_creds, mock_get_service, mock_account, mock_db):
    """Test listing files when the Google Drive API returns an error."""

    mock_get_creds.return_value = MagicMock()
    mock_service = MagicMock()
    mock_get_service.return_value = mock_service
    mock_service.files.return_value.list.return_value.execute.side_effect = Exception("API error")

    files = gdrive_service.list_files(mock_account, mock_db)
    assert files == []


@patch("app.services.gdrive_service.get_drive_service")
@patch("app.services.gdrive_service.get_valid_credentials")
def test_get_account_info(mock_get_creds, mock_get_service, mock_account, mock_db):
    """Test successfully retrieving Google Drive account storage and user information."""

    mock_get_creds.return_value = MagicMock()
    mock_service = MagicMock()
    mock_get_service.return_value = mock_service

    mock_service.about.return_value.get.return_value.execute.return_value = {
        "user": {"emailAddress": "test@gmail.com"},
        "storageQuota": {"usage": "100", "limit": "1000"},
    }

    info = gdrive_service.get_account_info(mock_account, mock_db)

    assert info["email"] == "test@gmail.com"
    assert info["storage_used"] == 100
    assert info["storage_total"] == 1000


@patch("app.services.gdrive_service.get_drive_service")
@patch("app.services.gdrive_service.get_valid_credentials")
def test_get_account_info_error(mock_get_creds, mock_get_service, mock_account, mock_db):
    """Test retrieving account information when an API error occurs."""

    mock_get_creds.return_value = MagicMock()
    mock_get_service.return_value.about.return_value.get.return_value.execute.side_effect = (
        Exception("error")
    )

    info = gdrive_service.get_account_info(mock_account, mock_db)
    assert not info


@patch("app.services.gdrive_service.get_drive_service")
@patch("app.services.gdrive_service.get_valid_credentials")
def test_list_all_media(mock_get_creds, mock_get_service, mock_account, mock_db):
    """Test listing all media files across multiple pages of results."""

    mock_get_creds.return_value = MagicMock()
    mock_service = MagicMock()
    mock_get_service.return_value = mock_service

    mock_service.files.return_value.list.return_value.execute.side_effect = [
        {
            "files": [{"id": "m1", "name": "movie.mp4", "mimeType": "video/mp4"}],
            "nextPageToken": "token2",
        },
        {
            "files": [{"id": "p1", "name": "photo.jpg", "mimeType": "image/jpeg"}],
            "nextPageToken": None,
        },
    ]

    media = gdrive_service.list_all_media(mock_account, mock_db)

    assert len(media) == 2
    assert media[0]["name"] == "movie.mp4"
    assert media[1]["name"] == "photo.jpg"


@patch("app.services.gdrive_service.Credentials")
def test_get_valid_access_token_refresh_fail(mock_creds_class, mock_account, mock_db):
    """Test get_valid_access_token falling back to current token on refresh failure."""
    mock_creds = MagicMock()
    mock_creds.expired = True
    mock_creds.refresh.side_effect = Exception("failed")
    mock_creds.token = None
    mock_creds_class.return_value = mock_creds

    token = gdrive_service.get_valid_access_token(mock_account, mock_db)
    assert token == "old_token"


@patch("app.services.gdrive_service.get_valid_credentials")
def test_missing_credentials_scenarios(mock_get_creds, mock_account, mock_db):
    """Test various services when credentials cannot be obtained."""
    mock_get_creds.return_value = None

    assert not gdrive_service.list_files(mock_account, mock_db)
    assert not gdrive_service.get_account_info(mock_account, mock_db)
    assert not gdrive_service.list_all_media(mock_account, mock_db)


@patch("app.services.gdrive_service.get_drive_service")
@patch("app.services.gdrive_service.get_valid_credentials")
def test_list_all_media_error(mock_get_creds, mock_get_service, mock_account, mock_db):
    """Test list_all_media handling API errors."""
    mock_get_creds.return_value = MagicMock()
    mock_get_service.return_value.files.return_value.list.return_value.execute.side_effect = (
        Exception("fail")
    )

    media = gdrive_service.list_all_media(mock_account, mock_db)
    assert media == []
