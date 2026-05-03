"""Tests for the library service."""

from unittest.mock import MagicMock, patch

import pytest

from app.db import models
from app.services import library_service


@pytest.fixture
def mock_accounts():
    """Fixture to provide mock user accounts."""

    return [
        models.Account(email="g1@gmail.com", provider="gdrive", access_token="t1"),
        models.Account(email="m1@mega.nz", provider="mega", access_token="t2", refresh_token="p2"),
    ]


@pytest.mark.asyncio
@patch("app.services.library_service.gdrive_list")
@patch("app.services.library_service.get_mega_session")
@patch("app.services.library_service.mega_list")
async def test_list_all_files_parallel(
    mock_mega_list, mock_get_mega, mock_gdrive_list, mock_db, mock_accounts
):
    """Test listing all files from multiple providers in parallel."""

    mock_gdrive_list.return_value = [
        {"name": "file1", "type": "file", "provider": "gdrive", "id": "g1"}
    ]
    mock_session = MagicMock()
    mock_get_mega.return_value = mock_session
    mock_mega_list.return_value = [
        {"name": "file2", "type": "file", "provider": "mega", "id": "m1"}
    ]

    files = await library_service.list_all_files(mock_db, mock_accounts, "root")

    assert len(files) == 2
    mock_gdrive_list.assert_called_once()
    mock_mega_list.assert_called_once()


@pytest.mark.asyncio
@patch("app.services.library_service.gdrive_list")
@patch("app.services.library_service.get_mega_session")
@patch("app.services.library_service.mega_list")
async def test_list_all_files_error_handling(_mock_m, mock_gm, mock_g, mock_db, mock_accounts):
    """Test that listing all files handles provider-specific errors gracefully."""

    mock_g.side_effect = Exception("GDrive error")
    mock_gm.return_value = None  # MEGA session fail

    files = await library_service.list_all_files(mock_db, mock_accounts, "root")
    assert files == []


def test_inject_metadata(mock_db):
    """Test injecting metadata and watch history into file lists."""

    files = [{"name": "f1", "type": "file", "ids": {"gdrive": "fid1"}, "providers": ["gdrive"]}]

    # Mock metadata objects
    mock_meta = MagicMock()
    mock_meta.file_id = "fid1"
    mock_meta.duration = "120"
    mock_meta.width = 1920
    mock_meta.height = 1080
    mock_meta.updated_at = 123456789

    mock_history = MagicMock()
    mock_history.file_id = "fid1"
    mock_history.current_time = 60
    mock_history.duration = 120

    # Use the model-aware query results
    mock_db._query_results[models.FileMetadata] = [mock_meta]
    mock_db._query_results[models.WatchHistory] = [mock_history]

    with patch(
        "app.services.background_service.ThumbnailSyncManager.is_task_active",
        return_value=True,
    ):
        enriched = library_service.inject_metadata(mock_db, 1, files)

    assert str(enriched[0]["duration"]) == "120"
    assert enriched[0]["progress_percentage"] == 50
    assert enriched[0]["is_generating"] is True


def test_get_cached_folder(mock_db):
    """Test retrieving cached folder data from the database."""

    mock_cache = MagicMock()
    mock_cache.data = [{"name": "cached_file"}]
    mock_db._query_results[models.FolderCache] = [mock_cache]

    result = library_service.get_cached_folder(mock_db, 1, "folder1")
    assert result == [{"name": "cached_file"}]


def test_save_folder_cache_update(mock_db):
    """Test saving or updating folder data in the database cache."""

    mock_cache = MagicMock()
    mock_db._query_results[models.FolderCache] = [mock_cache]

    library_service.save_folder_cache(mock_db, 1, "folder1", [{"name": "new_data"}])
    assert mock_cache.data == [{"name": "new_data"}]
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_list_all_files_json_fail(mock_db, mock_accounts):
    """Test list_all_files with invalid JSON folder_id."""
    with patch("app.services.library_service.gdrive_list", return_value=[]):
        with patch("app.services.library_service.get_mega_session", return_value=None):
            files = await library_service.list_all_files(mock_db, mock_accounts, "invalid { json")
            # Should not raise exception, just return empty list or root listing
            assert isinstance(files, list)


@pytest.mark.asyncio
async def test_list_all_files_account_mismatch(mock_db, mock_accounts):
    """Test list_all_files with account-specific folder ID that doesn't match."""
    # Folder ID for a different GDrive account
    folder_id = "other@gmail.com:folder1"
    with patch("app.services.library_service.gdrive_list") as mock_list:
        await library_service.list_all_files(mock_db, mock_accounts, folder_id)
        # Should NOT call gdrive_list for g1@gmail.com because of the email mismatch
        mock_list.assert_not_called()


@pytest.mark.asyncio
@patch("app.services.library_service.get_mega_session")
@patch("app.services.library_service.invalidate_session")
async def test_list_all_files_mega_error_invalidate(
    mock_invalidate, mock_get_mega, mock_db, mock_accounts
):
    """Test MEGA session invalidation on error."""
    mock_get_mega.return_value = MagicMock()
    with patch("app.services.library_service.mega_list", side_effect=Exception("API Error")):
        await library_service.list_all_files(mock_db, mock_accounts, "root")
        mock_invalidate.assert_called_once()


def test_inject_metadata_no_user(mock_db):
    """Test metadata injection with no authenticated user."""
    files = [{"name": "f1", "type": "file", "ids": {"gdrive": "fid1"}}]
    mock_db._query_results[models.FileMetadata] = []
    enriched = library_service.inject_metadata(mock_db, -1, files)
    assert enriched[0]["is_generating"] is False


def test_save_folder_cache_new(mock_db):
    """Test saving a new folder cache entry."""
    mock_db._query_results[models.FolderCache] = []
    library_service.save_folder_cache(mock_db, 1, "new_folder", [{"n": "f"}])
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()
