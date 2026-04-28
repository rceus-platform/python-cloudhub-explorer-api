"""Mega Cloud Service: handles authentication, session persistence, and file/link retrieval."""

import hashlib
import hmac
import json
import logging
import os
import pickle
import time

from mega import Mega

from app.core.config import settings

logger = logging.getLogger(__name__)


def _mask_email(email: str) -> str:
    """Produce a masked version of an email address for logging."""
    if not email or "@" not in email:
        return "unknown"
    try:
        user, domain = email.split("@", 1)
        if len(user) <= 2:
            return f"*@{domain}"
        return f"{user[0]}***{user[-1]}@{domain}"
    except Exception:
        return "invalid-email"


def _get_hmac(data: bytes) -> str:
    """Generate HMAC signature for data integrity."""
    key = os.environ.get("SECRET_KEY", "default-secret-key").encode()
    return hmac.new(key, data, hashlib.sha256).hexdigest()


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
    """Load a pickled Mega session from disk with integrity check."""

    path = _session_file(email)
    sig_path = f"{path}.sig"
    if not os.path.exists(path) or not os.path.exists(sig_path):
        return None

    try:
        with open(path, "rb") as f:
            data = f.read()
        with open(sig_path, "r", encoding="utf-8") as f:
            expected_sig = f.read().strip()
        if not hmac.compare_digest(_get_hmac(data), expected_sig):
            logger.error("Session integrity check failed for %s", _mask_email(email))
            return None

        m = pickle.loads(data)
        m.get_quota()
        logger.info("Reusing disk session for %s", _mask_email(email))
        return m
    except Exception:
        logger.exception(
            "Disk session for %s is invalid or expired. Removing.", _mask_email(email)
        )
        for p in [path, sig_path]:
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
        return None


def _save_session(email: str, m) -> None:
    """Pickle the Mega client to disk with HMAC signature."""

    path = _session_file(email)
    sig_path = f"{path}.sig"
    try:
        # Ensure directory has restricted permissions
        os.chmod(_ensure_sessions_dir(), 0o700)
        data = pickle.dumps(m)
        sig = _get_hmac(data)
        with open(path, "wb") as f:
            f.write(data)
        with open(sig_path, "w", encoding="utf-8") as f:
            f.write(sig)

        # Restrict file permissions
        os.chmod(path, 0o600)
        os.chmod(sig_path, 0o600)
        logger.info("Saved Mega session to disk for %s", _mask_email(email))
    except Exception:
        logger.exception(
            "Could not save Mega session to disk for %s", _mask_email(email)
        )


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
        logger.info("Attempting fresh Mega login for %s...", _mask_email(email))
        mega = Mega()
        m = mega.login(email, password)
        logger.info("Successfully logged into Mega for %s", _mask_email(email))

        _save_session(email, m)
        _MEGA_SESSIONS[email] = m
        return m

    except json.JSONDecodeError:
        logger.error(
            "Mega API returned non-JSON for %s. "
            "This usually means invalid credentials or rate limiting.",
            _mask_email(email),
        )
        return None
    except Exception:
        logger.exception(
            "Unexpected error logging into Mega for %s", _mask_email(email)
        )
        return None


def get_mega_session(email: str, password: str | None = None):
    """Return a live Mega session, reusing one if possible."""

    if not email:
        return None

    m = _MEGA_SESSIONS.get(email)
    if m is not None:
        logger.info("Reusing in-memory session for %s", _mask_email(email))
        return m

    m = _load_session(email)
    if m is not None:
        _MEGA_SESSIONS[email] = m
        return m

    if not password:
        return None

    return login_to_mega(email, password)


def invalidate_session(email: str) -> None:
    """Remove a broken or expired session from both memory and disk."""

    logger.info("Invalidating Mega session for %s", _mask_email(email))
    _MEGA_SESSIONS.pop(email, None)

    path = _session_file(email)
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        logger.exception("Could not remove session file for %s", _mask_email(email))


def get_mega_download_url(m, file_id: str):
    """Get a downloadable URL for a file in the MEGA account."""

    try:
        file_data = m.get_files()

        if file_id not in file_data:
            return None

        return m.get_link(file_id)
    except Exception:
        logger.exception("Error fetching files for Mega account")
        return None


def list_files(
    m, folder_id: str = "root", account_id: int = None, account_email: str = None
):
    """List files from MEGA with proper folder navigation."""

    try:
        logger.info("Fetching files from Mega for folder_id: %s", folder_id)
        files = m.get_files()
        logger.info(
            "Successfully fetched %d nodes from Mega", len(files) if files else 0
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

            t_val = file_data.get("t")
            if t_val in [2, 3, 4]:
                continue

            file_type = "folder" if t_val == 1 else "file"
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
    except Exception:
        logger.exception("Error listing files from Mega for account %s", account_email)
        return []
