"""Tests for the files routes."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.main import app

client = TestClient(app)


@pytest.fixture
def mock_db():
    """Fixture for a mock database session."""

    db = MagicMock()
    app.dependency_overrides[get_db] = lambda: db
    yield db
    app.dependency_overrides.clear()


@pytest.fixture
def mock_user():
    """Fixture for a mock authenticated user."""

    user = MagicMock()
    user.id = 1
    app.dependency_overrides[get_current_user] = lambda: user
    yield user
    app.dependency_overrides.clear()


@pytest.fixture
def mock_library_service():
    """Fixture for a mock library service."""

    with patch("app.api.routes.files.library_service") as mock:
        yield mock


@pytest.mark.usefixtures("mock_db", "mock_user")
def test_list_files_authenticated(mock_library_service):
    """Test listing files from a library with authentication."""

    # Mock library service calls
    mock_library_service.list_all_files = AsyncMock(
        return_value=[{"id": "file1", "name": "movie.mp4", "provider": "gdrive"}]
    )
    mock_library_service.inject_metadata.return_value = [
        {"id": "file1", "name": "movie.mp4", "provider": "gdrive", "thumbnail": None}
    ]

    response = client.get("/files/", params={"folder_id": "root"})

    assert response.status_code == 200
    data = response.json()
    assert len(data["files"]) == 1
    assert data["files"][0]["name"] == "movie.mp4"


def test_list_files_forbidden_without_token():
    """Test that protected resources are inaccessible without a token."""

    # Attempting to access a protected route or library without auth
    response = client.get("/files/", params={"folder_id": "root"})
    assert response.status_code == 401
