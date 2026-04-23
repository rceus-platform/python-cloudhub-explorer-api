"""
Mega Cloud Service

Responsibilities:
- Manage Mega.nz authentication and session persistence
- Handle session caching (memory and disk) with throttle guards
- Fetch file listings and download links from Mega
"""

import hashlib
import json
import logging
import os
import pickle
import time

from mega import Mega

from app.core.config import settings

logger = logging.getLogger(__name__)

MIN_LOGIN_INTERVAL: int = 60

_MEGA_SESSIONS: dict = {}
_last_login_attempt: dict[str, float] = {}


def _ensure_sessions_dir() -> str:
    """Return the session directory path, creating it if necessary."""

    path = settings.MEGA_SESSION_DIR
    os.makedirs(path, exist_ok=True)
    return path


def _session_file(email: str) -> str:
    """Return the path to the pickle file for the given email address."""

    digest = hashlib.sha256(email.encode()).hexdigest()
    return os.path.join(_ensure_sessions_dir(), f"{digest}.pickle")


def _load_session(email: str):
    """Load a pickled Mega session from disk and validate it."""

    path = _session_file(email)
    if not os.path.exists(path):
        return None

    try:
        with open(path, "rb") as f:
            m = pickle.load(f)

        m.get_quota()
        logger.info("Reusing disk session for %s", email)
        return m
    except Exception as e:
        logger.warning(
            "Disk session for %s is invalid or expired (%s). Removing.", email, e
        )
        try:
            os.remove(path)
        except OSError:
            pass
        return None


def _save_session(email: str, m) -> None:
    """Pickle the logged-in Mega client to disk."""

    path = _session_file(email)
    try:
        with open(path, "wb") as f:
            pickle.dump(m, f)
        logger.info("Saved Mega session to disk for %s", email)
    except Exception as e:
        logger.warning("Could not save Mega session to disk for %s: %s", email, e)


def login_to_mega(email: str, password: str):
    """Perform a fresh credential-based login to MEGA with throttle guard."""

    if not email or not password:
        logger.warning("Skipping Mega login: email or password missing.")
        return None

    now = time.monotonic()
    last = _last_login_attempt.get(email, 0.0)
    if now - last < MIN_LOGIN_INTERVAL:
        wait = int(MIN_LOGIN_INTERVAL - (now - last))
        logger.warning(
            "Skipping Mega login for %s: throttled, retry in %ds.", email, wait
        )
        return None

    _last_login_attempt[email] = now

    try:
        logger.info("Attempting fresh Mega login for %s...", email)
        mega = Mega()
        m = mega.login(email, password)
        logger.info("Successfully logged into Mega for %s", email)

        _save_session(email, m)
        _MEGA_SESSIONS[email] = m
        return m

    except json.JSONDecodeError:
        logger.error(
            "Mega API returned non-JSON for %s. "
            "This usually means invalid credentials or rate limiting.",
            email
        )
        return None
    except Exception as e:
        logger.error("Unexpected error logging into Mega for %s: %s", email, e)
        return None


def get_mega_session(email: str, password: str):
    """Return a live Mega session, reusing one if possible."""

    if not email or not password:
        return None

    m = _MEGA_SESSIONS.get(email)
    if m is not None:
        logger.info("Reusing in-memory session for %s", email)
        return m

    m = _load_session(email)
    if m is not None:
        _MEGA_SESSIONS[email] = m
        return m

    return login_to_mega(email, password)


def invalidate_session(email: str) -> None:
    """Remove a broken or expired session from both memory and disk."""

    logger.info("Invalidating Mega session for %s", email)
    _MEGA_SESSIONS.pop(email, None)

    path = _session_file(email)
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as e:
        logger.warning("Could not remove session file for %s: %s", email, e)


def get_mega_download_url(m, file_id: str):
    """Get a downloadable URL for a file in the MEGA account."""

    try:
        file_data = m.get_files()

        if file_id not in file_data:
            return None

        return m.get_link(file_id)
    except Exception as e:
        logger.error("Error getting Mega download link: %s", e)
        return None


def list_files(
    m, folder_id: str = "root", account_id: int = None, account_email: str = None
):
    """List files from MEGA with proper folder navigation."""

    try:
        logger.info("Fetching files from Mega for folder_id: %s", folder_id)
        files = m.get_files()
        logger.info(
            "Successfully fetched %d nodes from Mega",
            len(files) if files else 0
        )

        if not files:
            return []

        root_handle = None
        if folder_id == "root":
            for h, data in files.items():
                if data.get("t") == 2:
                    root_handle = h
                    break
            logger.info("Identified Mega root handle: %s", root_handle)

        result = []

        for file_id, file_data in files.items():
            parent_id = file_data.get("p")

            if folder_id == "root":
                if parent_id != root_handle:
                    continue
            else:
                if parent_id != folder_id:
                    continue

            if file_data.get("t") in [2, 3, 4]:
                continue

            file_type = "folder" if file_data["t"] == 1 else "file"
            name = file_data.get("a", {}).get("n", "unknown")

            result.append(
                {
                    "id": file_id,
                    "name": name,
                    "type": file_type,
                    "size": file_data.get("s", 0),
                    "provider": "mega",
                    "account_id": account_id,
                    "account_email": account_email,
                }
            )

        logger.info("Returning %d items from Mega", len(result))
        return result
    except Exception as e:
        logger.error("Error listing files from Mega: %s", e)
        return []
