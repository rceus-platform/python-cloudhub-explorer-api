"""File Cache Module.

Responsibilities:
- Provide an in-memory TTL-based cache for folder listings
- Manage cache expiration and invalidation
- Ensure namespaced storage to prevent data leakage between users

Boundaries:
- Does not persist data to disk
- Does not handle serialization (stored as Python objects)
"""

import time
from typing import Any

# In-memory storage: _CACHE[key] = (timestamp, data)
_CACHE: dict[str, tuple[float, Any]] = {}

# Default time-to-live in seconds (30 minutes)
DEFAULT_TTL: int = 30 * 60

def _make_key(user_id: int, folder_id: str) -> str:
    """Build a namespaced cache key to isolate user data."""

    return f"user:{user_id}:folder:{folder_id}"

def get(user_id: int, folder_id: str) -> Any | None:
    """Retrieve non-expired data from the cache; returns None on miss or expiry."""

    key = _make_key(user_id, folder_id)
    entry = _CACHE.get(key)
    if entry is None:
        return None

    timestamp, data = entry
    if time.monotonic() - timestamp > DEFAULT_TTL:
        del _CACHE[key]
        return None
    return data

def set_data(user_id: int, folder_id: str, data: Any) -> None:
    """Persist data in the cache with the current monotonic timestamp."""

    key = _make_key(user_id, folder_id)
    _CACHE[key] = (time.monotonic(), data)

def invalidate(user_id: int, folder_id: str) -> None:
    """Manually remove a specific folder entry from the cache."""

    key = _make_key(user_id, folder_id)
    _CACHE.pop(key, None)

def invalidate_all(user_id: int) -> None:
    """Wipe all cached entries for a specific user."""

    prefix = f"user:{user_id}:"
    stale_keys = [k for k in _CACHE if k.startswith(prefix)]
    for k in stale_keys:
        del _CACHE[k]
