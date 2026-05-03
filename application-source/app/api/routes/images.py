"""Images API Module.

Responsibilities:
- Provide secure image delivery through provider-aware proxying
- Optionally resize images for lightweight previews

Boundaries:
- Does not modify file indexing or metadata persistence
- Does not expose direct provider URLs to clients
"""

import io

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from PIL import Image
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import get_current_user_optional
from app.db import models
from app.db.session import get_db
from app.services import account_service
from app.services.gdrive_service import get_valid_access_token
from app.utils.file_utils import get_media_type

router = APIRouter()


def _resolve_account(
    db: Session,
    user_id: int,
    provider: str,
    file_id: str,
) -> tuple[models.Account | None, str]:
    if ":" in file_id:
        email, raw_id = file_id.split(":", 1)
        account = account_service.get_account_by_email(db, user_id, provider, email)
        return account, raw_id

    return account_service.get_provider_account(db, user_id, provider), file_id


def _build_upstream_request(
    provider: str,
    real_file_id: str,
    account: models.Account,
    db: Session,
) -> tuple[str, dict[str, str]]:
    headers: dict[str, str] = {}

    if provider == "gdrive":
        token = get_valid_access_token(account, db)
        headers["Authorization"] = f"Bearer {token}"
        return f"https://www.googleapis.com/drive/v3/files/{real_file_id}?alt=media", headers

    if provider == "mega":
        headers["X-Mega-Email"] = str(account.access_token)
        headers["X-Mega-Password"] = str(account.refresh_token)
        if settings.INTERNAL_SECRET:
            headers["X-Internal-Secret"] = settings.INTERNAL_SECRET
        return f"http://localhost:4000/stream?fileId={real_file_id}", headers

    raise HTTPException(status_code=400, detail="Unsupported provider")


@router.get("/{image_id}")
async def get_image(
    image_id: str,
    provider: str = Query(...),
    file_name: str = Query(""),
    w: int | None = Query(default=None, ge=1, le=4096),
    h: int | None = Query(default=None, ge=1, le=4096),
    db: Session = Depends(get_db),
    user: models.User | None = Depends(get_current_user_optional),
):
    user_id = int(user.id) if user else -1  # type: ignore[arg-type]
    account, real_file_id = _resolve_account(db, user_id, provider, image_id)
    if not account:
        raise HTTPException(status_code=404, detail="Credentials not found")

    upstream_url, upstream_headers = _build_upstream_request(provider, real_file_id, account, db)
    requested_media_type = get_media_type(file_name)

    if not requested_media_type.startswith("image/") and file_name:
        raise HTTPException(status_code=400, detail="Requested file is not an image")

    should_resize = w is not None or h is not None

    if should_resize:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(upstream_url, headers=upstream_headers, follow_redirects=True)
            if resp.status_code == 401 and provider == "gdrive":
                token = get_valid_access_token(account, db)
                upstream_headers["Authorization"] = f"Bearer {token}"
                resp = await client.get(upstream_url, headers=upstream_headers, follow_redirects=True)

            if resp.status_code >= 400:
                raise HTTPException(status_code=resp.status_code, detail="Unable to fetch image")

            with Image.open(io.BytesIO(resp.content)) as image:
                image = image.convert("RGB")
                target_w = w or image.width
                target_h = h or image.height
                image.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)

                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=85, optimize=True)
                payload = buffer.getvalue()

        return Response(
            content=payload,
            media_type="image/jpeg",
            headers={
                "Content-Length": str(len(payload)),
                "Cache-Control": "private, max-age=120",
                "Content-Disposition": "inline",
            },
        )

    timeout = httpx.Timeout(connect=10, read=None, write=30, pool=30)
    source_headers: dict[str, str] = {}

    # Validate upstream response before returning stream, so we don't emit blank 200 responses.
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            async with client.stream(
                "GET", upstream_url, headers=upstream_headers, follow_redirects=True
            ) as source_resp:
                if source_resp.status_code == 401 and provider == "gdrive":
                    token = get_valid_access_token(account, db)
                    upstream_headers["Authorization"] = f"Bearer {token}"
                    async with client.stream(
                        "GET", upstream_url, headers=upstream_headers, follow_redirects=True
                    ) as retry_resp:
                        if retry_resp.status_code >= 400:
                            raise HTTPException(
                                status_code=retry_resp.status_code,
                                detail="Unable to fetch image",
                            )
                        source_headers = dict(retry_resp.headers)
                else:
                    if source_resp.status_code >= 400:
                        raise HTTPException(
                            status_code=source_resp.status_code,
                            detail="Unable to fetch image",
                        )
                    source_headers = dict(source_resp.headers)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail="Failed to connect to image source") from exc

    async def generate():
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "GET", upstream_url, headers=upstream_headers, follow_redirects=True
            ) as resp:
                if resp.status_code == 401 and provider == "gdrive":
                    token = get_valid_access_token(account, db)
                    upstream_headers["Authorization"] = f"Bearer {token}"
                    async with client.stream(
                        "GET", upstream_url, headers=upstream_headers, follow_redirects=True
                    ) as retry_resp:
                        if retry_resp.status_code >= 400:
                            raise HTTPException(
                                status_code=retry_resp.status_code,
                                detail="Unable to fetch image",
                            )
                        async for chunk in retry_resp.aiter_bytes(chunk_size=512 * 1024):
                            yield chunk
                    return

                if resp.status_code >= 400:
                    raise HTTPException(status_code=resp.status_code, detail="Unable to fetch image")

                async for chunk in resp.aiter_bytes(chunk_size=512 * 1024):
                    yield chunk

    resolved_type = source_headers.get("Content-Type") or source_headers.get("content-type")
    headers = {"Content-Disposition": "inline"}
    headers["Content-Type"] = (
        resolved_type
        if resolved_type and resolved_type.startswith("image/")
        else requested_media_type
        if requested_media_type.startswith("image/")
        else "image/jpeg"
    )

    content_length = source_headers.get("Content-Length") or source_headers.get("content-length")
    if content_length:
        headers["Content-Length"] = content_length

    return StreamingResponse(generate(), headers=headers)
