"""Google Drive Service Module.

Responsibilities:
- Manage Google OAuth2 credential refreshing and persistence
- Interact with Google Drive API v3 to list and manage files
- Provide unified file objects compatible with the application's merged library

Boundaries:
- Does not handle user authentication flows (delegated to account_service)
- Does not handle file merging (delegated to library_service)
"""

from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build  # type: ignore[import]
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import models


def get_valid_credentials(account: models.Account, db: Session) -> Credentials:
    """Retrieve and automatically refresh Google OAuth2 credentials from the database."""

    creds = Credentials(
        token=account.access_token,
        refresh_token=account.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
    )

    if creds.expired or not creds.valid:
        try:
            creds.refresh(Request())  # type: ignore[misc]
            account.access_token = creds.token  # type: ignore[attr-defined]
            db.commit()
            db.refresh(account)
        except Exception:  # type: ignore[misc]
            return None  # type: ignore[return-value]

    return creds


def get_drive_service(creds: Credentials):  # type: ignore[no-untyped-def]
    """Initialize a Google Drive v3 client service instance with discovery cache disabled."""

    return build("drive", "v3", credentials=creds, cache_discovery=False)  # type: ignore[no-any-return]


def list_files(
    account: models.Account, db: Session, folder_id: str = "root"
) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    """Fetch files for a specific folder handle from Google Drive."""

    creds = get_valid_credentials(account, db)
    if not creds:
        return []  # type: ignore[return-value]

    service = get_drive_service(creds)  # type: ignore[assignment]
    query = (
        f"'{folder_id}' in parents and trashed=false"
        if folder_id != "root"
        else "'root' in parents and trashed=false"
    )

    try:
        results = (  # type: ignore[assignment]
            service.files()  # type: ignore[union-attr]
            .list(
                q=query,
                pageSize=50,
                fields="files(id, name, mimeType, size, thumbnailLink)",
            )
            .execute()
        )
        files = results.get("files", [])  # type: ignore[union-attr]
    except Exception as e:
        print(f"GDrive API error for {account.email}: {e}")
        files = []

    return [  # type: ignore[return-value]
        {
            "id": f"{account.email}:{f['id']}",  # type: ignore[index]
            "name": f["name"],  # type: ignore[index]
            "type": "folder" if "folder" in f["mimeType"] else "file",  # type: ignore[index]
            "size": int(f.get("size", 0)) if f.get("size") else 0,  # type: ignore[union-attr]
            "thumbnail_url": f.get("thumbnailLink"),  # type: ignore[union-attr]
            "provider": "gdrive",
        }
        for f in files  # type: ignore[union-attr]
    ]  # type: ignore[return-value]


def get_valid_access_token(account: models.Account, db: Session) -> str:
    """Check and return a valid access token, refreshing only if expired."""

    creds = Credentials(
        token=account.access_token,
        refresh_token=account.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
    )

    if creds.expired or not creds.valid:
        try:
            creds.refresh(Request())  # type: ignore[misc]
            account.access_token = creds.token  # type: ignore[attr-defined]
            db.commit()
        except Exception:
            # Fallback to current token if refresh fails
            pass

    return creds.token if creds.token else str(account.access_token)  # type: ignore[return-value]


def get_account_info(account: models.Account, db: Session) -> dict[str, Any]:
    """Retrieve email and storage quota for a Google Drive account."""

    creds = get_valid_credentials(account, db)
    if not creds:
        return {}

    service = get_drive_service(creds)
    try:
        about = service.about().get(fields="user(emailAddress), storageQuota").execute()
        return {
            "email": about["user"]["emailAddress"],
            "storage_used": int(about["storageQuota"]["usage"]),
            "storage_total": int(about["storageQuota"]["limit"]),
        }
    except Exception:
        return {}


def list_all_media(account: models.Account, db: Session) -> list[dict[str, Any]]:
    """Recursively find all media files in a Google Drive account using broad search."""

    creds = get_valid_credentials(account, db)
    if not creds:
        return []

    service = get_drive_service(creds)
    # Search for common media mime types across the entire drive
    query = "trashed=false and (mimeType contains 'video/' or mimeType contains 'image/')"

    files = []
    page_token = None
    try:
        while True:
            results = (
                service.files()
                .list(
                    q=query,
                    pageSize=1000,
                    fields="nextPageToken, files(id, name, mimeType, size)",
                    pageToken=page_token,
                )
                .execute()
            )
            files.extend(results.get("files", []))
            page_token = results.get("nextPageToken")
            if not page_token:
                break
    except Exception as e:
        print(f"GDrive search error for {account.email}: {e}")

    return [
        {
            "id": f"{account.email}:{f['id']}",
            "name": f["name"],
            "type": "file",
            "size": int(f.get("size", 0)) if f.get("size") else 0,
            "provider": "gdrive",
        }
        for f in files
    ]
