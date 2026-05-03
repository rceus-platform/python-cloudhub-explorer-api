"""Mega Service Module for managing MEGA.nz sessions, file operations, and storage metrics."""

import hashlib
import logging
import os
import pickle
import threading
import time
from typing import Any

from mega import Mega  # type: ignore[import]

from app.core.config import settings

logger = logging.getLogger(__name__)

# Throttling and session configuration
MIN_LOGIN_INTERVAL: int = 60
_MEGA_SESSIONS: dict[str, Any] = {}
_MEGA_LOCKS: dict[str, threading.Lock] = {}
_last_login_attempt: dict[str, float] = {}


def _ensure_sessions_dir() -> str:
    """Ensure the directory for storing session pickles exists."""

    path = settings.MEGA_SESSION_DIR
    os.makedirs(path, exist_ok=True)
    return path


def _session_file(email: str) -> str:
    """Generate a stable, safe filesystem path for an account session."""

    digest = hashlib.sha256(email.encode()).hexdigest()
    return os.path.join(_ensure_sessions_dir(), f"{digest}.pickle")


def _load_session(email: str):
    """Attempt to load and validate a cached session from disk."""

    path = _session_file(email)
    if not os.path.exists(path):
        return None

    try:
        with open(path, "rb") as f:
            m = pickle.load(f)
        # Lightweight validation call
        m.get_quota()
        return m
    except Exception:
        try:
            os.remove(path)
        except OSError:
            pass
        return None


def _save_session(email: str, m: Any) -> None:  # type: ignore[misc]
    """Persist a live Mega client session to disk as a pickle."""

    path = _session_file(email)
    try:
        with open(path, "wb") as f:
            pickle.dump(m, f)
    except Exception as e:
        logger.warning("Could not save Mega session for %s: %s", email, e)


def login_to_mega(email: str, password: str):
    """Perform a throttled credential-based login to the MEGA API."""

    if not email or not password:
        return None

    now = time.monotonic()
    last = _last_login_attempt.get(email, 0.0)
    if now - last < MIN_LOGIN_INTERVAL:
        logger.info(
            "MEGA login throttled for %s (retry in %ds)",
            email,
            int(MIN_LOGIN_INTERVAL - (now - last)),
        )
        return None

    _last_login_attempt[email] = now
    try:
        mega = Mega()
        m = mega.login(email, password)  # type: ignore[no-untyped-call]
        _save_session(email, m)
        _MEGA_SESSIONS[email] = m
        return m
    except Exception:
        logger.exception("MEGA login failed for %s", email)
        return None


def get_mega_session(email: str, password: str) -> Any:  # type: ignore[no-untyped-def]
    """Retrieve a live Mega session using memory, disk, or fresh login in order."""

    if not email or not password:
        return None

    m = _MEGA_SESSIONS.get(email)
    if m is not None:
        return m

    m = _load_session(email)
    if m is not None:
        _MEGA_SESSIONS[email] = m
        return m

    m = login_to_mega(email, password)
    if m is None:
        # Clear any stale disk session that might block future attempts
        invalidate_session(email)
    return m


def invalidate_session(email: str) -> None:
    """Clean up broken or expired sessions from all cache layers."""

    _MEGA_SESSIONS.pop(email, None)
    _MEGA_LOCKS.pop(email, None)
    path = _session_file(email)
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def _get_lock(email: str) -> threading.Lock:
    """Get or create a thread lock for a specific account email."""
    if email not in _MEGA_LOCKS:
        _MEGA_LOCKS[email] = threading.Lock()
    return _MEGA_LOCKS[email]


def list_files(m: Any, account_email: str, folder_id: str = "root"):  # type: ignore[no-untyped-def]
    """List nodes from MEGA, filtering for the specified folder scope."""

    lock = _get_lock(account_email)
    try:
        with lock:
            files = m.get_files()  # type: ignore[union-attr]
        if not files:
            return []  # type: ignore[return-value]

        root_handle = None
        if folder_id == "root":
            for h, data in files.items():  # type: ignore[union-attr]
                if data.get("t") == 2:  # type: ignore[union-attr]
                    root_handle = h
                    break

        result = []
        for file_id, file_data in files.items():  # type: ignore[union-attr]
            parent_id = file_data.get("p")  # type: ignore[union-attr]
            if folder_id == "root":
                if parent_id != root_handle:
                    continue
            else:
                if parent_id != folder_id:
                    continue

            if file_data.get("t") in [2, 3, 4]:  # type: ignore[union-attr]
                continue

            result.append(  # type: ignore[union-attr]
                {  # type: ignore[union-attr]
                    "id": f"{account_email}:{file_id}",
                    "name": file_data.get("a", {}).get("n", "unknown"),
                    "type": ("folder" if file_data.get("t") == 1 else "file"),
                    "size": file_data.get("s", 0),
                    "provider": "mega",
                }
            )
        return result  # type: ignore[return-value]
    except Exception:
        logger.exception("MEGA API error")
        return []  # type: ignore[return-value]


def get_storage_info(m: Any) -> dict[str, Any]:
    """Retrieve storage quota for a MEGA account."""

    email = getattr(m, "email", None)
    lock = _get_lock(email) if email else threading.Lock()
    try:
        # Try get_storage_space first which usually returns a dict with 'used' and 'total' in bytes
        try:
            with lock:
                quota = m.get_storage_space()
            logger.debug("MEGA storage_space response: %s", quota)
        except Exception:
            with lock:
                quota = m.get_quota()
            logger.debug("MEGA quota response: %s", quota)

        # Handle dictionary response (standard for get_storage_space)
        if isinstance(quota, dict):
            total = quota.get("total") or quota.get("space_total") or 0
            used = quota.get("used") or quota.get("space_used") or 0

            # If values are small (e.g. total < 1,000,000), they are likely in MB
            if total > 0 and total < 1024 * 1024:
                total *= 1024 * 1024
                used *= 1024 * 1024
        elif isinstance(quota, (int, float)):
            # If it's a single number, it's usually the total quota in MB
            total = quota * 1024 * 1024
            used = 0
        else:
            total = 0
            used = 0

        return {
            "storage_used": int(used),
            "storage_total": int(total),
        }
    except Exception:
        logger.exception("MEGA storage info error")
        return {"storage_used": 0, "storage_total": 0}
