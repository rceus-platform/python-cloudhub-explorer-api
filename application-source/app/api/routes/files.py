"""Files API Router: handles multi-provider file listing, metadata merging, and secure streaming."""


import json
import logging
from urllib.parse import quote

import requests
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import get_current_user, get_current_user_optional
from app.db import models
from app.db.session import get_db
from app.services.gdrive_service import (
    get_valid_access_token,
)
from app.services.gdrive_service import list_files as gdrive_list
from app.services.mega_service import (
    get_mega_session,
    invalidate_session,
)
from app.services.mega_service import list_files as mega_list
from app.utils.folder_merger import merge_files

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/")
def list_files(
    folder_id: str = Query("root"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """List files and folders for the current user from all connected providers"""

    accounts = db.query(models.Account).filter(models.Account.user_id == user.id).all()

    all_file_lists = []

    if folder_id == "root" and settings.MEGA_USERNAME and settings.MEGA_PASSWORD:
        try:
            m = get_mega_session(settings.MEGA_USERNAME, settings.MEGA_PASSWORD)
            if m:
                files = mega_list(
                    m,
                    folder_id,
                    account_id=0,
                    account_email=settings.MEGA_USERNAME,
                )
                if files:
                    all_file_lists.append(files)
        except Exception:
            logger.exception("Error with env-configured Mega login")
            invalidate_session(settings.MEGA_USERNAME)

    if folder_id == "root":
        for acc in accounts:
            try:
                if acc.provider == "gdrive":
                    files = gdrive_list(acc, db, folder_id)

                elif acc.provider == "mega":
                    m = get_mega_session(acc.access_token, acc.refresh_token)
                    if not m:
                        continue
                    files = mega_list(
                        m, folder_id, account_id=acc.id, account_email=acc.email
                    )

                else:
                    continue

                if files:
                    all_file_lists.append(files)
            except Exception:
                logger.exception("Error listing files for provider %s", acc.provider)
                if acc.provider == "mega":
                    invalidate_session(acc.access_token)
                continue

        merged_files = merge_files(all_file_lists)
        logger.info("Successfully merged %d files for user %s from multiple providers", len(merged_files), user.id)
        return {"folder_id": folder_id, "files": merged_files}

    try:
        folder_map = json.loads(folder_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid folder_id format") from exc

    for acc in accounts:
        provider = acc.provider

        if provider not in folder_map:
            continue

        provider_folder_id = folder_map[provider]

        try:
            if provider == "gdrive":
                files = gdrive_list(acc, db, provider_folder_id)

            elif provider == "mega":
                m = get_mega_session(acc.access_token, acc.refresh_token)
                if not m:
                    continue
                files = mega_list(
                    m, provider_folder_id, account_id=acc.id, account_email=acc.email
                )

            else:
                continue

            if files:
                all_file_lists.append(files)
        except Exception:
            logger.exception("Error listing files for provider %s", provider)
            if provider == "mega":
                invalidate_session(acc.access_token)
            continue

    merged_files = merge_files(all_file_lists)

    return {"folder_id": folder_id, "files": merged_files}


@router.get("/stream")
def stream_file(
    request: Request,
    provider: str,
    file_id: str,
    _file_name: str,
    account_id: int = Query(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user_optional),
):
    """Stream a file from the specified provider with range support"""

    if provider not in ["gdrive", "mega"]:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")

    account = None

    if user is not None:
        query = db.query(models.Account).filter(
            models.Account.user_id == user.id,
            models.Account.provider == provider,
        )

        if account_id is not None:
            query = query.filter(models.Account.id == account_id)

        account = query.first()

    if account is None and provider == "mega":
        if settings.MEGA_USERNAME and settings.MEGA_PASSWORD:

            class _EnvMegaAccount:
                access_token = settings.MEGA_USERNAME
                refresh_token = settings.MEGA_PASSWORD

            account = _EnvMegaAccount()

    if not account:
        raise HTTPException(
            status_code=404,
            detail=f"No linked {provider} account found and no environment credentials configured",
        )

    headers = {}
    range_header = request.headers.get("Range")
    if range_header:
        headers["Range"] = range_header

    url = ""
    if provider == "gdrive":
        access_token = get_valid_access_token(account, db)

        url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"

        headers["Authorization"] = f"Bearer {access_token}"

    elif provider == "mega":
        stream_url = (
            f"{settings.STREAM_SERVICE_URL}/stream?"
            f"email={quote(account.access_token)}&"
            f"fileId={quote(file_id)}"
        )

        headers = {}
        range_header = request.headers.get("Range")
        if range_header:
            headers["Range"] = range_header

        try:
            response = requests.get(
                stream_url, headers=headers, stream=True, timeout=60
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as exc:
            logger.exception("Error connecting to Mega stream service for file %s", file_id)
            raise HTTPException(
                status_code=502, detail="Error communicating with streaming service"
            ) from exc

        def generate_mega():
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    yield chunk

        return StreamingResponse(
            generate_mega(),
            status_code=response.status_code,
            headers={
                "Content-Type": response.headers.get("Content-Type", "video/mp4"),
                "Content-Length": response.headers.get("Content-Length", ""),
                "Accept-Ranges": "bytes",
                "Content-Range": response.headers.get("Content-Range", ""),
                "Content-Disposition": "inline",
            },
        )

    try:
        response = requests.get(url, headers=headers, stream=True, timeout=60)
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        logger.exception("Error streaming from provider %s for file %s", provider, file_id)
        raise HTTPException(
            status_code=502, detail=f"Error streaming from {provider}"
        ) from exc

    def generate_drive():
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                yield chunk

    return StreamingResponse(
        generate_drive(),
        status_code=response.status_code,
        headers={
            "Content-Type": response.headers.get("Content-Type", "video/mp4"),
            "Content-Length": response.headers.get("Content-Length", ""),
            "Accept-Ranges": "bytes",
            "Content-Range": response.headers.get("Content-Range", ""),
            "Content-Disposition": "inline",
        },
    )
