"""Integration tests for the video route."""

from unittest.mock import MagicMock

from app.db import models


def test_save_video_progress_new(client, mock_db):
    """Test saving watch progress for a video that has no previous record."""

    payload = {"file_id": "fid1", "current_time": 100.0, "duration": 500.0}
    # Mock no existing record
    mock_db._query_results[models.WatchHistory] = []

    response = client.post("/video/progress", json=payload)

    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()


def test_save_video_progress_update(client, mock_db):
    """Test updating existing watch progress for a video."""

    payload = {"file_id": "fid1", "current_time": 200.0, "duration": 500.0}
    # Mock existing record
    record = MagicMock()
    mock_db._query_results[models.WatchHistory] = [record]

    response = client.post("/video/progress", json=payload)

    assert response.status_code == 200
    assert record.current_time == 200.0
    mock_db.commit.assert_called_once()


def test_get_video_state(client, mock_db):
    """Test retrieving the saved watch state for a video."""

    record = MagicMock()
    record.current_time = 123.0
    record.duration = 456.0
    mock_db._query_results[models.WatchHistory] = [record]

    response = client.get("/video/state/fid1")

    assert response.status_code == 200
    assert response.json() == {"current_time": 123.0, "duration": 456.0}


def test_get_video_state_not_found(client, mock_db):
    """Test retrieving video state when no previous record exists (should return 0)."""

    mock_db._query_results[models.WatchHistory] = []

    response = client.get("/video/state/fid1")

    assert response.status_code == 200
    assert response.json() == {"current_time": 0, "duration": 0}
