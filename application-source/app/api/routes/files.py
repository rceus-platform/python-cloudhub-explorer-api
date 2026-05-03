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

import asyncio
import io
import json
import logging
import os
import threading

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from PIL import Image
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import get_current_user, get_current_user_optional
from app.db import models
from app.db.schemas import FileListResponse, ThumbnailUpdateResponse
from app.db.session import get_db
from app.services import (
    account_service,
    background_service,
    file_cache,
    library_service,
    thumbnail_service,
)
from app.services.gdrive_service import get_valid_access_token
from app.utils.file_utils import get_media_type

logger = logging.getLogger(__name__)

router = APIRouter()

# Global semaphore to limit concurrent thumbnail extractions (prevents OOM on 1GB VMs)
thumbnail_semaphore = threading.Semaphore(1)


def _resolve_account(
    db: Session,
    user_id: int,
    provider: str,
    file_id: str,
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
            # Ensure background tasks are enqueued for missing thumbnails when serving from cache
            background_service.set_active_folder(user_id, folder_id)
            await background_service.enqueue_folder_thumbnails(user_id, folder_id, db_cached)

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

    # Trigger background thumbnail generation for the current folder
    background_service.set_active_folder(user_id, folder_id)
    await background_service.enqueue_folder_thumbnails(user_id, folder_id, merged_files)

    # Inject metadata (thumbnails, duration, watch history)
    enriched_files = library_service.inject_metadata(db, user_id, merged_files)

    result = FileListResponse(folder_id=folder_id, files=enriched_files)
    file_cache.set_data(user_id, folder_id, result.model_dump())
    return result


@router.get("/stream")
async def stream_file(
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

    async def generate():
        timeout = httpx.Timeout(connect=10, read=None, write=30, pool=30)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                # First attempt
                async with client.stream("GET", url, headers=headers, follow_redirects=True) as response:
                    # If unauthorized, try refreshing once
                    if response.status_code == 401 and provider == "gdrive":
                        logger.info("Stream unauthorized (401), attempting token refresh...")
                        new_token = get_valid_access_token(account, db)
                        headers["Authorization"] = f"Bearer {new_token}"
                        async with client.stream(
                            "GET", url, headers=headers, follow_redirects=True
                        ) as retry_response:
                            if retry_response.status_code >= 400:
                                logger.error("Stream source error %d", retry_response.status_code)
                                return
                            async for chunk in retry_response.aiter_bytes(chunk_size=1024 * 1024):
                                yield chunk
                        return

                    if response.status_code >= 400:
                        logger.error("Stream source error %d", response.status_code)
                        return

                    async for chunk in response.aiter_bytes(chunk_size=1024 * 1024):
                        yield chunk
            except Exception:
                logger.exception("Error during streaming generation")

    # To support seeking, we must handle Range requests and return 206 Partial Content
    # We'll do a quick HEAD or GET with stream=True to get the source headers
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            # We use a stream request to get headers without downloading the body
            async with client.stream(
                "GET", url, headers=headers, follow_redirects=True
            ) as source_resp:
                if source_resp.status_code == 401 and provider == "gdrive":
                    new_token = get_valid_access_token(account, db)
                    headers["Authorization"] = f"Bearer {new_token}"
                    # Re-open stream with new token
                    async with client.stream(
                        "GET", url, headers=headers, follow_redirects=True
                    ) as retry_resp:
                        source_headers = dict(retry_resp.headers)
                        status_code = retry_resp.status_code
                else:
                    source_headers = dict(source_resp.headers)
                    status_code = source_resp.status_code
        except Exception as e:
            logger.error("Failed to connect to stream source: %s", e)
            raise HTTPException(status_code=502, detail="Failed to connect to stream source") from e

    # Proxy relevant headers
    response_headers = {
        "Content-Type": get_media_type(file_name),
        "Accept-Ranges": "bytes",
        "Content-Disposition": "inline",
    }

    content_range = source_headers.get("Content-Range") or source_headers.get("content-range")
    if content_range:
        response_headers["Content-Range"] = content_range

    content_length = source_headers.get("Content-Length") or source_headers.get("content-length")
    if content_length:
        response_headers["Content-Length"] = content_length

    for header_name in ["Cache-Control", "ETag", "Last-Modified"]:
        value = source_headers.get(header_name) or source_headers.get(header_name.lower())
        if value:
            response_headers[header_name] = value

    return StreamingResponse(
        generate(),
        status_code=status_code if status_code in [200, 206] else 200,
        headers=response_headers,
    )


@router.get("/thumbnail")
async def get_thumbnail(
    provider: str,
    file_id: str,
    file_name: str | None = None,
    v: str | None = None,
    timestamp: int | None = None,
    db: Session = Depends(get_db),
    user: models.User | None = Depends(get_current_user_optional),
):
    """Retrieve or extract a thumbnail for a given file."""

    cache_path = thumbnail_service.get_cache_path(file_id, timestamp)
    logger.info(
        "Request for %s (v=%s, ts=%s) checking path: %s",
        file_id,
        v,
        timestamp,
        os.path.abspath(cache_path),
    )

    # Check cache/db first for standard thumbnails
    if timestamp is None:
        metadata = (
            db.query(models.FileMetadata).filter(models.FileMetadata.file_id == file_id).first()
        )
        # If file exists on disk, return it even if metadata is slightly out of sync
        if os.path.exists(cache_path):
            logger.info("Found thumbnail on disk for %s, returning immediately.", file_id)
            return FileResponse(cache_path, media_type="image/jpeg")

        if metadata and metadata.thumbnail_path:  # type: ignore[return-value]
            thumbnail_path_str = str(metadata.thumbnail_path)
            # We already checked cache_path above, but this handles potential path mismatches in DB
            if thumbnail_path_str:
                logger.debug(
                    "Metadata exists for %s, but file not found on disk at %s", file_id, cache_path
                )

    # Resolve account and stream URL
    user_id = int(user.id) if user else -1  # type: ignore[arg-type]
    account, real_file_id = _resolve_account(db, user_id, provider, file_id)

    media_type = get_media_type(file_name or "")
    is_image = media_type.startswith("image/")

    # If standard thumbnail is missing, trigger background generation and return placeholder
    if timestamp is None:
        file_info = {
            "ids": {provider: file_id},
            "name": file_name,
            "type": "file",
        }
        # Fire and forget generation
        asyncio.create_task(background_service.enqueue_thumbnail(user_id, "root", file_info))

        placeholder = "placeholder-image.png" if is_image else "placeholder-video.png"
        return FileResponse(
            os.path.join("assets", placeholder),
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    # On-demand extraction for custom timestamps (modal previews)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    token = get_valid_access_token(account, db) if provider == "gdrive" else None
    stream_url = (
        f"https://www.googleapis.com/drive/v3/files/{real_file_id}?alt=media"
        if provider == "gdrive"
        else f"http://localhost:4000/stream?fileId={real_file_id}"
    )

    try:
        # Security headers for internal stream proxy
        headers = {}
        if provider == "gdrive" and token:
            headers["Authorization"] = f"Bearer {token}"
        elif provider == "mega":
            headers["X-Mega-Email"] = str(account.access_token)
            headers["X-Mega-Password"] = str(account.refresh_token)
            if settings.INTERNAL_SECRET:
                headers["X-Internal-Secret"] = settings.INTERNAL_SECRET

        # For custom timestamps, we still do synchronous extraction to provide immediate preview
        with thumbnail_semaphore:
            _duration, _width, _height = thumbnail_service.extract_video_frame(
                stream_url, headers, cache_path, timestamp
            )

        return FileResponse(cache_path)
    except Exception:
        logger.exception("Thumbnail extraction failed, returning placeholder")
        placeholder = "placeholder-video.png"
        return FileResponse(os.path.join("assets", placeholder))


@router.patch("/{file_id}/thumbnail", response_model=ThumbnailUpdateResponse)
async def update_thumbnail(
    file_id: str,
    provider: str = Query(...),
    timestamp: int | None = Query(None),
    duration: float | None = Query(None),
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

        extracted_duration, _, _ = thumbnail_service.extract_video_frame(
            stream_url, headers, cache_path, timestamp
        )
        if duration is None and extracted_duration is not None:
            duration = extracted_duration
    else:
        raise HTTPException(status_code=400, detail="Missing timestamp or file")

    thumbnail_service.save_metadata(db, file_id, provider, None, duration, None, None)
    metadata = db.query(models.FileMetadata).filter(models.FileMetadata.file_id == file_id).first()
    updated_at = int(metadata.updated_at) if metadata else 0  # type: ignore[arg-type]

    # Invalidate cache so frontend polling picks it up
    file_cache.invalidate_all(int(user.id))

    return ThumbnailUpdateResponse(success=True, updated_at=updated_at)
