"""Tests for the in-memory file cache service."""

import time

import pytest

from app.services import file_cache


@pytest.fixture(autouse=True)
def clear_cache():
    """Ensure the cache is empty before each test."""

    file_cache._CACHE.clear()
    yield


def test_cache_set_and_get():
    """Test setting and getting data from the cache."""

    user_id = 1
    folder_id = "root"
    data = [{"id": "f1", "name": "file1"}]

    file_cache.set_data(user_id, folder_id, data)
    assert file_cache.get(user_id, folder_id) == data


def test_cache_miss():
    """Test cache behavior on a miss (data not found)."""

    assert file_cache.get(1, "non-existent") is None


def test_cache_expiry():
    """Test cache behavior when data has expired."""

    user_id = 1
    folder_id = "expiring"
    data = "some data"

    file_cache.set_data(user_id, folder_id, data)

    # Manually backdate the entry to simulate expiry
    key = file_cache._make_key(user_id, folder_id)
    file_cache._CACHE[key] = (time.monotonic() - file_cache.DEFAULT_TTL - 1, data)

    assert file_cache.get(user_id, folder_id) is None
    assert key not in file_cache._CACHE


def test_invalidate():
    """Test invalidating a specific cache entry."""

    user_id = 1
    folder_id = "to-be-deleted"
    file_cache.set_data(user_id, folder_id, "data")

    file_cache.invalidate(user_id, folder_id)
    assert file_cache.get(user_id, folder_id) is None


def test_invalidate_all():
    """Test invalidating all cache entries for a specific user."""

    user_id = 1
    file_cache.set_data(user_id, "f1", "d1")
    file_cache.set_data(user_id, "f2", "d2")
    file_cache.set_data(2, "f3", "d3")

    file_cache.invalidate_all(user_id)

    assert file_cache.get(user_id, "f1") is None
    assert file_cache.get(user_id, "f2") is None
    assert file_cache.get(2, "f3") == "d3"
