"""Tests for the background sync service."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.background_service import ThumbnailSyncManager


@pytest.fixture(autouse=True)
def reset_manager():
    """Reset the singleton state of ThumbnailSyncManager before each test."""
    ThumbnailSyncManager._queue_obj = None
    ThumbnailSyncManager._in_progress = set()
    ThumbnailSyncManager._active_folders = {}
    ThumbnailSyncManager._worker_tasks = []
    ThumbnailSyncManager._semaphore = None
    ThumbnailSyncManager._is_running = False
    ThumbnailSyncManager._task_counter = 0
    ThumbnailSyncManager._queued_ids = set()
    yield


@pytest.mark.asyncio
async def test_enqueue_thumbnail():
    """Test enqueuing a thumbnail generation task."""
    file_info = {"name": "test.mp4", "ids": {"gdrive": "f1"}}
    user_id = 1
    folder_id = "folder1"

    with patch("os.path.exists", return_value=False):
        await ThumbnailSyncManager.enqueue_thumbnail(user_id, folder_id, file_info)

    queue = ThumbnailSyncManager.get_queue()
    assert queue.qsize() == 1
    _, _, uid, fid, info = await queue.get()
    assert uid == user_id
    assert fid == folder_id
    assert info == file_info
    assert "f1" in ThumbnailSyncManager._queued_ids


@pytest.mark.asyncio
async def test_enqueue_thumbnail_skip_existing():
    """Test that existing thumbnails are skipped during enqueuing."""
    file_info = {"name": "test.mp4", "ids": {"gdrive": "f1"}}

    with patch("os.path.exists", return_value=True):
        await ThumbnailSyncManager.enqueue_thumbnail(1, "folder1", file_info)

    assert ThumbnailSyncManager.get_queue().qsize() == 0


@pytest.mark.asyncio
async def test_set_active_folder():
    """Test setting the active folder for a user."""
    ThumbnailSyncManager.set_active_folder(1, "folder123")
    assert ThumbnailSyncManager._active_folders[1] == "folder123"


@pytest.mark.asyncio
async def test_worker_loop_skips_inactive_folder():
    """Test that the worker loop skips tasks for folders that are not currently active."""
    # Setup queue with a task for an inactive folder
    file_info = {"name": "test.mp4", "ids": {"gdrive": "f1"}}
    ThumbnailSyncManager.set_active_folder(1, "active_folder")

    queue = ThumbnailSyncManager.get_queue()
    # priority > 0 and active_folder != folder_id
    await queue.put((1, 1, 1, "inactive_folder", file_info))
    ThumbnailSyncManager._queued_ids.add("f1")

    # Run one iteration of worker loop
    with patch("app.services.background_service.AdaptiveController"):
        # We need to mock _process_file_thumbnail to make sure it's NOT called
        with patch.object(
            ThumbnailSyncManager, "_process_file_thumbnail", new_callable=AsyncMock
        ) as mock_process:
            # We'll use a timeout because worker_loop is an infinite loop
            try:
                await asyncio.wait_for(ThumbnailSyncManager._worker_loop(0), timeout=0.1)
            except asyncio.TimeoutError:
                pass

            mock_process.assert_not_called()
            assert "f1" not in ThumbnailSyncManager._queued_ids


@pytest.mark.asyncio
@patch("app.services.background_service.SessionLocal")
@patch("app.services.background_service.thumbnail_service")
@patch("app.services.background_service.account_service")
@patch("app.services.background_service.get_valid_access_token")
async def test_process_file_thumbnail_gdrive(
    mock_get_token, mock_account_service, mock_thumb_service, mock_session_local
):
    """Test processing a Google Drive file thumbnail."""
    file_info = {"name": "test.mp4", "ids": {"gdrive": "f1"}}
    user_id = 1

    mock_db = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_db

    mock_account = MagicMock()
    mock_account_service.get_provider_account.return_value = mock_account
    mock_get_token.return_value = "fake_token"

    mock_thumb_service.get_cache_path.return_value = "/tmp/cache.jpg"
    mock_thumb_service.extract_video_frame.return_value = (10.0, 1920, 1080)

    with patch("os.path.exists", return_value=False):
        await ThumbnailSyncManager._process_file_thumbnail(user_id, file_info, delay_seconds=0)

    mock_thumb_service.save_metadata.assert_called_once()


@pytest.mark.asyncio
@patch("app.services.background_service.SessionLocal")
@patch("app.services.background_service.account_service")
@patch("app.services.background_service.ThumbnailSyncManager.enqueue_thumbnail")
async def test_sync_thumbnails_gdrive(mock_enqueue, mock_account_service, mock_session_local):
    """Test synchronizing thumbnails for all Google Drive media."""
    user_id = 1
    mock_db = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_db

    mock_account = MagicMock()
    mock_account.provider = "gdrive"
    mock_account.email = "test@gdrive.com"
    mock_account_service.get_user_accounts.return_value = [mock_account]

    # Use MagicMock instead of AsyncMock for functions called via to_thread
    with patch("app.services.gdrive_service.list_all_media") as mock_gdrive_sync:
        mock_gdrive_sync.return_value = [
            {"ids": {"gdrive": "f1"}, "name": "video.mp4", "type": "file"}
        ]

        await ThumbnailSyncManager.sync_thumbnails(user_id)

        mock_enqueue.assert_called_once()


@pytest.mark.asyncio
@patch("app.services.background_service.SessionLocal")
@patch("app.services.background_service.account_service")
@patch("app.services.background_service.ThumbnailSyncManager.enqueue_thumbnail")
async def test_sync_thumbnails_mega(mock_enqueue, mock_account_service, mock_session_local):
    """Test synchronizing thumbnails for all MEGA media."""
    user_id = 1
    mock_db = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_db

    mock_account = MagicMock()
    mock_account.provider = "mega"
    mock_account.email = "test@mega.nz"
    mock_account.access_token = "m_email"
    mock_account.refresh_token = "m_pass"
    mock_account_service.get_user_accounts.return_value = [mock_account]

    # Use MagicMock instead of AsyncMock for functions called via to_thread
    with patch("app.services.mega_service.get_mega_session") as mock_get_mega:
        mock_m = MagicMock()
        mock_get_mega.return_value = mock_m
        mock_m.get_files.return_value = {"h1": {"t": 0, "a": {"n": "movie.mp4"}}}

        await ThumbnailSyncManager.sync_thumbnails(user_id)

        mock_enqueue.assert_called_once()


@pytest.mark.asyncio
async def test_enqueue_thumbnail_no_ids():
    """Test enqueuing a thumbnail with no IDs."""
    await ThumbnailSyncManager.enqueue_thumbnail(1, "root", {"name": "test.mp4"})
    assert ThumbnailSyncManager.get_queue().qsize() == 0


@pytest.mark.asyncio
async def test_enqueue_thumbnail_in_progress():
    """Test enqueuing a thumbnail that is already in progress."""
    file_info = {"name": "test.mp4", "ids": {"gdrive": "f1"}}
    ThumbnailSyncManager._in_progress.add("f1")
    await ThumbnailSyncManager.enqueue_thumbnail(1, "root", file_info)
    assert ThumbnailSyncManager.get_queue().qsize() == 0


@pytest.mark.asyncio
async def test_enqueue_folder_thumbnails():
    """Test enqueuing multiple thumbnails in a folder."""
    files = [
        {"name": "t1.mp4", "ids": {"gdrive": "f1"}, "type": "file"},
        {"name": "t2.mp4", "ids": {"gdrive": "f2"}, "type": "file"},
        {"name": "subfolder", "type": "folder"},
    ]
    with patch("os.path.exists", return_value=False):
        await ThumbnailSyncManager.enqueue_folder_thumbnails(1, "root", files)
    assert ThumbnailSyncManager.get_queue().qsize() == 2


@pytest.mark.asyncio
async def test_sync_thumbnails_already_running():
    """Test starting a sync when one is already running."""
    ThumbnailSyncManager._is_running = True
    await ThumbnailSyncManager.sync_thumbnails(1)
    # If it didn't crash and returns immediately, it's correct.
    assert ThumbnailSyncManager._is_running is True


@pytest.mark.asyncio
@patch("app.services.background_service.SessionLocal")
async def test_sync_thumbnails_error(mock_session_local):
    """Test sync thumbnails handling exceptions."""
    mock_session_local.side_effect = Exception("DB Down")
    await ThumbnailSyncManager.sync_thumbnails(1)
    assert ThumbnailSyncManager._is_running is False


@pytest.mark.asyncio
async def test_worker_loop_no_file_id():
    """Test worker loop handling tasks with no file ID."""
    queue = ThumbnailSyncManager.get_queue()
    await queue.put((0, 1, 1, "root", {"name": "no_ids"}))
    with patch("app.services.background_service.AdaptiveController"):
        try:
            await asyncio.wait_for(ThumbnailSyncManager._worker_loop(0), timeout=0.1)
        except asyncio.TimeoutError:
            pass
    assert queue.qsize() == 0


@pytest.mark.asyncio
async def test_worker_loop_in_progress_skip():
    """Test worker loop skipping tasks already in progress."""
    file_info = {"name": "test.mp4", "ids": {"gdrive": "f1"}}
    ThumbnailSyncManager._in_progress.add("f1")
    queue = ThumbnailSyncManager.get_queue()
    await queue.put((0, 1, 1, "root", file_info))
    with patch("app.services.background_service.AdaptiveController"):
        with patch.object(ThumbnailSyncManager, "_process_file_thumbnail") as mock_process:
            try:
                await asyncio.wait_for(ThumbnailSyncManager._worker_loop(0), timeout=0.1)
            except asyncio.TimeoutError:
                pass
            mock_process.assert_not_called()


@pytest.mark.asyncio
async def test_worker_loop_root_priority_bypass():
    """Test that priority 0 (root) tasks bypass inactive folder check."""
    file_info = {"name": "test.mp4", "ids": {"gdrive": "f1"}}
    ThumbnailSyncManager.set_active_folder(1, "other_folder")
    queue = ThumbnailSyncManager.get_queue()
    await queue.put((0, 1, 1, "root", file_info))  # priority 0
    with patch("app.services.background_service.AdaptiveController"):
        with patch.object(
            ThumbnailSyncManager, "_process_file_thumbnail", new_callable=AsyncMock
        ) as mock_process:
            try:
                await asyncio.wait_for(ThumbnailSyncManager._worker_loop(0), timeout=0.1)
            except asyncio.TimeoutError:
                pass
            mock_process.assert_called_once()


@pytest.mark.asyncio
async def test_enqueue_active_folder_priority():
    """Test that files in the active folder get priority 1."""
    ThumbnailSyncManager.set_active_folder(1, "folder1")
    file_info = {"name": "test.mp4", "ids": {"gdrive": "f1"}}

    with patch("os.path.exists", return_value=False):
        await ThumbnailSyncManager.enqueue_thumbnail(1, "folder1", file_info)

    queue = ThumbnailSyncManager.get_queue()
    priority, _, _, _, _ = await queue.get()
    assert priority == 1


@pytest.mark.asyncio
async def test_worker_loop_exception_handling():
    """Test that the worker loop continues after an exception."""
    queue = ThumbnailSyncManager.get_queue()
    await queue.put((0, 1, 1, "root", {"ids": {"gdrive": "f1"}}))

    with patch("app.services.background_service.AdaptiveController"):
        with patch.object(
            ThumbnailSyncManager, "_process_file_thumbnail", side_effect=Exception("Fatal Error")
        ):
            try:
                await asyncio.wait_for(ThumbnailSyncManager._worker_loop(0), timeout=0.1)
            except asyncio.TimeoutError:
                pass
    assert queue.qsize() == 0  # Task was popped and processed (even if it failed)


@pytest.mark.asyncio
async def test_process_file_unsupported_media():
    """Test that unsupported media types are skipped."""
    file_info = {"name": "test.txt", "ids": {"gdrive": "f1"}}
    with patch("app.services.background_service.get_media_type", return_value="text/plain"):
        await ThumbnailSyncManager._process_file_thumbnail(1, file_info)
    # Should return early before any DB/Service calls
    assert ThumbnailSyncManager._in_progress == set()


@pytest.mark.asyncio
@patch("app.services.background_service.SessionLocal")
async def test_process_file_cache_hit_final(mock_session_local):
    """Test final existence check before heavy lifting."""
    file_info = {"name": "test.mp4", "ids": {"gdrive": "f1"}}
    with patch("os.path.exists", return_value=True):
        await ThumbnailSyncManager._process_file_thumbnail(1, file_info)
    mock_session_local.assert_not_called()


@pytest.mark.asyncio
@patch("app.services.background_service.SessionLocal")
@patch("app.services.background_service.account_service")
async def test_process_file_no_account(mock_account_service, _mock_session_local):
    """Test handling when account is not found in DB."""
    file_info = {"name": "test.mp4", "ids": {"gdrive": "f1"}}
    mock_account_service.get_provider_account.return_value = None
    with patch("os.path.exists", return_value=False):
        await ThumbnailSyncManager._process_file_thumbnail(1, file_info)
    mock_account_service.get_provider_account.assert_called_once()


@pytest.mark.asyncio
@patch("app.services.background_service.SessionLocal")
@patch("app.services.background_service.thumbnail_service")
@patch("app.services.background_service.account_service")
async def test_process_file_mega_success(
    mock_account_service, mock_thumb_service, _mock_session_local
):
    """Test processing a MEGA file thumbnail."""
    file_info = {"name": "test.mp4", "ids": {"mega": "f1"}}
    mock_account = MagicMock()
    mock_account.access_token = "email"
    mock_account.refresh_token = "pass"
    mock_account_service.get_provider_account.return_value = mock_account

    with patch("os.path.exists", return_value=False):
        await ThumbnailSyncManager._process_file_thumbnail(1, file_info, delay_seconds=0)

    # Check if mega headers were prepared
    call_args = mock_thumb_service.extract_video_frame.call_args
    headers = call_args[0][1]
    assert headers["X-Mega-Email"] == "email"


@pytest.mark.asyncio
@patch("app.services.background_service.SessionLocal")
@patch("app.services.background_service.thumbnail_service")
@patch("app.services.background_service.account_service")
async def test_process_file_image_success(
    mock_account_service, mock_thumb_service, _mock_session_local
):
    """Test processing an image file thumbnail."""
    file_info = {"name": "test.jpg", "ids": {"gdrive": "f1"}}
    mock_account_service.get_provider_account.return_value = MagicMock()

    with patch("os.path.exists", return_value=False):
        await ThumbnailSyncManager._process_file_thumbnail(1, file_info, delay_seconds=0)

    mock_thumb_service.process_image_thumbnail.assert_called_once()


@pytest.mark.asyncio
@patch("app.services.background_service.SessionLocal")
@patch("app.services.background_service.thumbnail_service")
@patch("app.services.background_service.account_service")
async def test_process_file_failure_path(
    mock_account_service, mock_thumb_service, mock_session_local
):
    """Test processing failure and metadata save fallback."""
    file_info = {"name": "test.mp4", "ids": {"gdrive": "f1"}}
    mock_account_service.get_provider_account.return_value = MagicMock()
    mock_thumb_service.extract_video_frame.side_effect = Exception("FFmpeg failed")
    mock_thumb_service.get_cache_path.return_value = "/tmp/f1.jpg"

    mock_db = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_db

    with patch("os.path.exists", return_value=False):
        await ThumbnailSyncManager._process_file_thumbnail(1, file_info, delay_seconds=0)

    # Should save metadata with None values on failure
    mock_thumb_service.save_metadata.assert_called_with(
        mock_db, "f1", "gdrive", "test.mp4", None, None, None
    )


@pytest.mark.asyncio
@patch("app.services.background_service.SessionLocal")
@patch("app.services.background_service.thumbnail_service")
@patch("app.services.background_service.account_service")
async def test_process_file_mega_email_split(
    mock_account_service, mock_thumb_service, mock_session_local
):
    """Test processing a file ID with email prefix (MEGA/GDRIVE format)."""
    file_info = {"name": "test.mp4", "ids": {"mega": "email@test.com:f1"}}
    mock_account_service.get_account_by_email.return_value = MagicMock()
    mock_thumb_service.get_cache_path.return_value = "/tmp/f1.jpg"
    mock_thumb_service.extract_video_frame.return_value = (0, 0, 0)

    mock_db = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_db

    with patch("os.path.exists", return_value=False):
        with patch("app.services.background_service.get_media_type", return_value="video/mp4"):
            await ThumbnailSyncManager._process_file_thumbnail(1, file_info, delay_seconds=0)

    mock_account_service.get_account_by_email.assert_called_once_with(
        mock_db, 1, "mega", "email@test.com"
    )
