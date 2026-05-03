"""Shared fixtures for all tests."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.main import app
from app.services import file_cache
from app.services.background_service import ThumbnailSyncManager


@pytest.fixture
def mock_db():
    """Fixture for a mock database session with model-aware querying."""

    db = MagicMock()

    # Store results for different models
    query_results = {}

    # The default return value for query()
    default_query = MagicMock()
    db.query.return_value = default_query

    def mock_query(model):
        if model in query_results:
            q = MagicMock()
            results = query_results.get(model, [])
            q.filter.return_value.all.return_value = results
            q.filter.return_value.first.return_value = results[0] if results else None
            q.filter.return_value.filter.return_value.first.return_value = (
                results[0] if results else None
            )
            q.filter.return_value.order_by.return_value.first.return_value = (
                results[0] if results else None
            )
            return q
        return default_query

    db.query.side_effect = mock_query
    db._query_results = query_results
    return db


@pytest.fixture
def mock_user():
    """Fixture for a mock authenticated user."""

    user = MagicMock()
    user.id = 1
    user.username = "testuser"
    return user


@pytest.fixture
def client(mock_db, mock_user):
    """Fixture for the FastAPI TestClient with pre-configured overrides."""

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_user] = lambda: mock_user

    # Reset singleton/global states
    file_cache._CACHE.clear()
    ThumbnailSyncManager._queued_ids = set()
    ThumbnailSyncManager._active_folders = {}

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
