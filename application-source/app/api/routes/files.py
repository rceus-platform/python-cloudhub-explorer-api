"""Files API Module.

Responsibilities:
- Provide endpoints for file browsing and navigation
- Handle media streaming and thumbnail retrieval
- Manage custom thumbnail uploads and captures

Boundaries:
- Logic for account resolution delegated to account_service
- Logic for library merging delegated to library_service
- Logic for media processing delegated to thumbnail_service
"""

import io
import json
import os
import threading

import requests
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from PIL import Image
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import get_current_user, get_current_user_optional
from app.db import models
from app.db.schemas import FileListResponse, ThumbnailUpdateResponse
from app.db.session import get_db
from app.services import account_service, file_cache, library_service, thumbnail_service
from app.services.gdrive_service import get_valid_access_token
from app.utils.file_utils import get_media_type

router = APIRouter()

# Global semaphore to limit concurrent thumbnail extractions (prevents OOM on small VMs)
thumbnail_semaphore = threading.Semaphore(2)


def _resolve_account(
    db: Session, user_id: int, provider: str, file_id: str
) -> tuple[models.Account | None, str]:
    """Extract account email from file_id and resolve the account credentials."""

    if ":" in file_id:
        email, raw_id = file_id.split(":", 1)
        account = account_service.get_account_by_email(db, user_id, provider, email)
        return account, raw_id

    # Backward compatibility for non-prefixed IDs (fallback to last account)
    return account_service.get_provider_account(db, user_id, provider), file_id


@router.get("/", response_model=FileListResponse)
async def list_files(
    folder_id: str = Query("root"),
    refresh: bool = Query(False),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> FileListResponse:
    """Retrieve a merged list of files from all linked cloud accounts."""

    user_id = int(user.id)  # type: ignore[arg-type]

    # Normalize folder_id if it's a JSON string to ensure consistent cache keys
    if folder_id != "root":
        try:
            data = json.loads(folder_id)
            if isinstance(data, dict):
                folder_id = json.dumps(data, sort_keys=True)
        except (json.JSONDecodeError, TypeError):
            pass

    # 1. Check in-memory TTL cache
    if not refresh:
        cached = file_cache.get(user_id, folder_id)
        if cached is not None:
            return cached

    # 2. Check database persistent cache
    if not refresh:
        db_cached = library_service.get_cached_folder(db, user_id, folder_id)
        if db_cached:
            # Re-inject dynamic metadata (watch progress) into cached structure
            enriched_files = library_service.inject_metadata(db, user_id, db_cached)
            result = FileListResponse(folder_id=folder_id, files=enriched_files)
            file_cache.set_data(user_id, folder_id, result.model_dump())
            return result

    accounts = account_service.get_user_accounts(db, user_id)

    # Resolve folder mapping for merged directories
    target_folder_id = folder_id
    if folder_id != "root":
        try:
            folder_map = json.loads(folder_id)
            # Filter accounts to only those present in the folder map
            accounts = [acc for acc in accounts if acc.provider in folder_map]
        except (json.JSONDecodeError, TypeError) as exc:
            raise HTTPException(status_code=400, detail="Invalid folder_id format") from exc

    # 3. Fetch from cloud accounts (Final fallback or if refresh=True)
    merged_files = await library_service.list_all_files(db, accounts, target_folder_id)

    # Save to database cache before enriching with user-specific session data
    library_service.save_folder_cache(db, user_id, folder_id, merged_files)

    # Inject metadata (thumbnails, duration, watch history)
    enriched_files = library_service.inject_metadata(db, user_id, merged_files)

    result = FileListResponse(folder_id=folder_id, files=enriched_files)
    file_cache.set_data(user_id, folder_id, result.model_dump())
    return result


@router.get("/stream")
def stream_file(
    request: Request,
    provider: str,
    file_id: str,
    db: Session = Depends(get_db),
    user: models.User | None = Depends(get_current_user_optional),
):
    """Proxy video streams from cloud providers with range support."""

    user_id = int(user.id) if user else -1  # type: ignore[arg-type]
    account, real_file_id = _resolve_account(db, user_id, provider, file_id)

    if not account:
        raise HTTPException(status_code=404, detail="Credentials not found")

    # Detect if it's an image to avoid range-based partial content issues
    file_name = request.query_params.get("file_name", "")
    is_image = get_media_type(file_name).startswith("image/")

    headers: dict[str, str] = {}
    range_header = request.headers.get("Range")
    if range_header and not is_image:
        headers["Range"] = range_header

    if provider == "gdrive":
        token = get_valid_access_token(account, db)
        url = f"https://www.googleapis.com/drive/v3/files/{real_file_id}?alt=media"
        headers["Authorization"] = f"Bearer {token}"
    elif provider == "mega":
        url = f"http://localhost:4000/stream?fileId={real_file_id}"
        headers["X-Mega-Email"] = str(account.access_token)
        headers["X-Mega-Password"] = str(account.refresh_token)
        if settings.INTERNAL_SECRET:
            headers["X-Internal-Secret"] = settings.INTERNAL_SECRET
    else:
        raise HTTPException(status_code=400, detail="Unsupported provider")

    response = requests.get(url, headers=headers, stream=True, timeout=30)
    print(f"DEBUG: Upstream {provider} response: {response.status_code}")
    print(f"DEBUG: Upstream headers: {dict(response.headers)}")

    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail="Stream source error")

    def generate():
        try:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    yield chunk
        finally:
            response.close()

    return StreamingResponse(
        generate(),
        status_code=response.status_code,
        headers={
            "Content-Type": response.headers.get("Content-Type", get_media_type(file_name)),
            "Content-Length": response.headers.get("Content-Length", ""),
            "Accept-Ranges": "bytes",
            "Content-Range": response.headers.get("Content-Range", ""),
            "Content-Disposition": "inline",
        },
    )


@router.get("/thumbnail")
def get_thumbnail(
    provider: str,
    file_id: str,
    file_name: str | None = None,
    timestamp: int | None = None,
    db: Session = Depends(get_db),
    user: models.User | None = Depends(get_current_user_optional),
):
    """Retrieve or extract a thumbnail for a given file."""

    cache_path = thumbnail_service.get_cache_path(file_id, timestamp)

    # Check cache/db first for standard thumbnails
    if timestamp is None:
        metadata = (
            db.query(models.FileMetadata).filter(models.FileMetadata.file_id == file_id).first()
        )
        if metadata and metadata.thumbnail_path:  # type: ignore[return-value]
            thumbnail_path_str = str(metadata.thumbnail_path)
            if thumbnail_path_str and os.path.exists(cache_path):
                return FileResponse(cache_path)

    # Resolve account and stream URL
    user_id = int(user.id) if user else -1  # type: ignore[arg-type]
    account, real_file_id = _resolve_account(db, user_id, provider, file_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    token = get_valid_access_token(account, db) if provider == "gdrive" else None
    stream_url = (
        f"https://www.googleapis.com/drive/v3/files/{real_file_id}?alt=media"
        if provider == "gdrive"
        else f"http://localhost:4000/stream?fileId={real_file_id}"
    )

    try:
        media_type = get_media_type(file_name or "")
        is_image = media_type.startswith("image/")

        # Security headers for internal stream proxy
        headers = {}
        if provider == "gdrive" and token:
            headers["Authorization"] = f"Bearer {token}"
        elif provider == "mega":
            headers["X-Mega-Email"] = str(account.access_token)
            headers["X-Mega-Password"] = str(account.refresh_token)
            if settings.INTERNAL_SECRET:
                headers["X-Internal-Secret"] = settings.INTERNAL_SECRET

        with thumbnail_semaphore:
            if is_image:
                thumbnail_service.process_image_thumbnail(stream_url, headers, cache_path)
                duration, width, height = 0, None, None
            else:
                duration, width, height = thumbnail_service.extract_video_frame(
                    stream_url, headers, cache_path, timestamp
                )

        if timestamp is None:
            thumbnail_service.save_metadata(
                db, file_id, provider, file_name, duration, width, height
            )

        return FileResponse(cache_path)
    except Exception as e:
        print(f"Thumbnail extraction failed: {e}")
        raise HTTPException(status_code=404, detail="Thumbnail not found") from e


@router.patch("/{file_id}/thumbnail", response_model=ThumbnailUpdateResponse)
async def update_thumbnail(
    file_id: str,
    provider: str = Query(...),
    timestamp: int | None = Query(None),
    file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> ThumbnailUpdateResponse:
    """Update a file's thumbnail via manual upload or timestamp capture."""

    cache_path = thumbnail_service.get_cache_path(file_id)

    if file:
        content = await file.read()
        img = Image.open(io.BytesIO(content))
        img.thumbnail((1280, 720))
        img.save(cache_path, "JPEG", quality=85, optimize=True)
    elif timestamp is not None:
        user_id = int(user.id)  # type: ignore[arg-type]
        account, real_file_id = _resolve_account(db, user_id, provider, file_id)
        if not account:
            raise HTTPException(status_code=401, detail="Account not found")

        token = get_valid_access_token(account, db) if provider == "gdrive" else None
        stream_url = (
            f"https://www.googleapis.com/drive/v3/files/{real_file_id}?alt=media"
            if provider == "gdrive"
            else f"http://localhost:4000/stream?fileId={real_file_id}"
        )

        # Security headers for internal stream proxy
        headers = {}
        if provider == "gdrive" and token:
            headers["Authorization"] = f"Bearer {token}"
        elif provider == "mega":
            headers["X-Mega-Email"] = str(account.access_token)
            headers["X-Mega-Password"] = str(account.refresh_token)
            if settings.INTERNAL_SECRET:
                headers["X-Internal-Secret"] = settings.INTERNAL_SECRET

        thumbnail_service.extract_video_frame(stream_url, headers, cache_path, timestamp)
    else:
        raise HTTPException(status_code=400, detail="Missing timestamp or file")

    thumbnail_service.save_metadata(db, file_id, provider, None, None, None, None)
    metadata = db.query(models.FileMetadata).filter(models.FileMetadata.file_id == file_id).first()
    updated_at = int(metadata.updated_at) if metadata else 0  # type: ignore[arg-type]
    return ThumbnailUpdateResponse(success=True, updated_at=updated_at)
