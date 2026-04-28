"""Google Drive Service: handles OAuth credentials, token refresh, and file listing."""

import logging

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import models

logger = logging.getLogger(__name__)


def get_valid_credentials(account: models.Account, db: Session):
    """Check if access token is valid, refresh if needed, and update DB."""

    creds = Credentials(
        token=account.access_token,
        refresh_token=account.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
    )

    if creds.expired or not creds.valid:
        try:
            creds.refresh(Request())
            account.access_token = creds.token
            db.commit()
            db.refresh(account)
        except Exception:
            logger.exception("Failed to refresh Google token for account %s", account.id)
            return None

    return creds


def get_drive_service(creds: Credentials):
    """Build Google Drive service"""

    service = build("drive", "v3", credentials=creds)
    return service


def list_files(account: models.Account, db: Session, folder_id: str = "root"):
    """Fetch files from Google Drive with auto token refresh"""

    creds = get_valid_credentials(account, db)
    if not creds:
        return []

    service = get_drive_service(creds)

    if folder_id == "root":
        query = "'root' in parents and trashed=false"
    else:
        query = f"'{folder_id}' in parents and trashed=false"

    results = (
        service.files()
        .list(q=query, pageSize=50, fields="files(id, name, mimeType, size)")
        .execute()
    )

    files = results.get("files", [])

    return [
        {
            "id": f["id"],
            "name": f["name"],
            "type": "folder" if "folder" in f["mimeType"] else "file",
            "size": int(f.get("size", 0)) if f.get("size") else 0,
            "provider": "gdrive",
            "account_id": account.id,
            "account_email": account.email,
        }
        for f in files
    ]


def get_valid_access_token(account, db):
    """Always ensure fresh access token BEFORE use"""

    creds = Credentials(
        token=account.access_token,
        refresh_token=account.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
    )

    try:
        creds.refresh(Request())
        account.access_token = creds.token
        db.commit()
    except Exception:
        logger.exception("Failed to force-refresh access token for account %s", account.id)
        raise

    return creds.token
