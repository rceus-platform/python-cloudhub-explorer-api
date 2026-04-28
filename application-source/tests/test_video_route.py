"""Tests for the video routes."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.session import get_db
from app.core.dependencies import get_current_user

client = TestClient(app)


@pytest.fixture
def mock_db():
    """Fixture for a mock database session."""

    db = MagicMock()
    app.dependency_overrides[get_db] = lambda: db
    yield db
    app.dependency_overrides.clear()


@pytest.fixture
def mock_current_user():
    """Fixture for a mock current user."""

    user = MagicMock()
    user.id = 1
    app.dependency_overrides[get_current_user] = lambda: user
    yield user
    app.dependency_overrides.clear()


@pytest.mark.usefixtures("mock_current_user")
def test_save_video_progress_new_record(mock_db):
    """Test saving video progress for a new file."""

    # Mock no existing record
    mock_db.query.return_value.filter.return_value.first.return_value = None

    response = client.post(
        "/video/progress",
        json={"file_id": "vid123", "current_time": 100, "duration": 300},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()


@pytest.mark.usefixtures("mock_current_user")
def test_save_video_progress_update_existing(mock_db):
    """Test updating existing video progress."""

    # Mock existing record
    mock_record = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_record

    response = client.post(
        "/video/progress",
        json={"file_id": "vid123", "current_time": 150, "duration": 300},
    )

    assert response.status_code == 200
    assert mock_record.current_time == 150
    mock_db.commit.assert_called_once()


@pytest.mark.usefixtures("mock_current_user")
def test_get_video_state_exists(mock_db):
    """Test retrieving existing video progress state."""

    # Mock existing record
    mock_record = MagicMock()
    mock_record.current_time = 120
    mock_record.duration = 600
    mock_db.query.return_value.filter.return_value.first.return_value = mock_record

    response = client.get("/video/state/vid123")

    assert response.status_code == 200
    data = response.json()
    assert data["current_time"] == 120
    assert data["duration"] == 600


@pytest.mark.usefixtures("mock_current_user")
def test_get_video_state_not_found(mock_db):
    """Test retrieving video state when no progress exists."""

    # Mock no record
    mock_db.query.return_value.filter.return_value.first.return_value = None

    response = client.get("/video/state/newvid")

    assert response.status_code == 200
    data = response.json()
    assert data["current_time"] == 0
    assert data["duration"] == 0
