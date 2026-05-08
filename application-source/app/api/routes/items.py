"""Items API Module.

Responsibilities:
- Expose CRUD endpoints for FileSystemItems (move, copy, rename, delete)
- Expose tag management and share link endpoints
- Expose folder/file creation endpoints
- Provide a filterable, sortable item listing endpoint

Boundaries:
- Business logic delegated to app.services.item_service
- Filter query construction delegated to app.api.deps.filter_engine
- Physical storage operations delegated to the Node.js microservice (via item_service)
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Query as SAQuery, Session

from app.api.deps.filter_engine import build_item_query
from app.core.dependencies import get_current_user
from app.db import models, schemas
from app.db.session import get_db
from app.services import item_service

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Item Listing (with search + filter + sort)
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[dict])
async def list_items(
    parent_id: str | None = Query(None, description="UUID of parent folder; omit for root"),
    q: SAQuery = Depends(build_item_query),
    user: models.User = Depends(get_current_user),
):
    """Return a filtered, sorted list of items in a given folder.

    Sorting is performed at the SQL level with folders always hoisted to the top.
    """
    user_id = int(user.id)  # type: ignore[arg-type]
    q = q.filter(
        models.FileSystemItem.user_id == user_id,
        models.FileSystemItem.parent_id == parent_id,
    )
    items = q.all()
    return [_serialize_item(i) for i in items]


# ---------------------------------------------------------------------------
# CRUD Operations
# ---------------------------------------------------------------------------


@router.post("/move", status_code=status.HTTP_200_OK)
async def move_items(
    payload: schemas.ItemMoveRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Move one or more items to a new parent folder."""
    user_id = int(user.id)  # type: ignore[arg-type]
    moved = await item_service.move_items(db, user_id, payload.item_ids, payload.destination_id)
    return {"moved": [i.id for i in moved]}


@router.post("/copy", status_code=status.HTTP_201_CREATED)
async def copy_items(
    payload: schemas.ItemCopyRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Deep-copy one or more items to a destination folder.

    When copying within the same folder, '_copy' is appended to the filename.
    """
    user_id = int(user.id)  # type: ignore[arg-type]
    copied = await item_service.copy_items(db, user_id, payload.item_ids, payload.destination_id)
    return {"copied": [_serialize_item(i) for i in copied]}


@router.patch("/{item_id}/rename", response_model=dict)
async def rename_item(
    item_id: str,
    payload: schemas.ItemRenameRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Rename a single file or folder."""
    user_id = int(user.id)  # type: ignore[arg-type]
    try:
        item = item_service.rename_item(db, user_id, item_id, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _serialize_item(item)


@router.delete("/remove", status_code=status.HTTP_200_OK)
async def delete_items(
    payload: schemas.ItemDeleteRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Bulk-delete items from the database and trigger physical storage removal."""
    user_id = int(user.id)  # type: ignore[arg-type]
    deleted_ids = await item_service.delete_items(db, user_id, payload.item_ids)
    return {"deleted": deleted_ids}


# ---------------------------------------------------------------------------
# Tag Management
# ---------------------------------------------------------------------------


@router.put("/{item_id}/tags", response_model=dict)
async def update_tags(
    item_id: str,
    payload: schemas.TagUpdateRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Replace the full tag set for an item (upserts new tags, removes stale ones)."""
    user_id = int(user.id)  # type: ignore[arg-type]
    try:
        item = item_service.set_item_tags(db, user_id, item_id, payload.tags)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _serialize_item(item)


# ---------------------------------------------------------------------------
# Share Links
# ---------------------------------------------------------------------------


@router.post("/share", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_share_link(
    payload: schemas.ShareLinkCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Generate a unique share link for a file or folder."""
    user_id = int(user.id)  # type: ignore[arg-type]

    expires_at: datetime | None = None
    if payload.expires_at:
        try:
            expires_at = datetime.fromisoformat(payload.expires_at)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid expires_at format") from exc

    try:
        link = item_service.create_share_link(
            db,
            user_id,
            payload.item_id,
            permission=payload.permission,
            expires_at=expires_at,
            password=payload.password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "hash": link.hash,
        "permission": link.permission,
        "expires_at": link.expires_at.isoformat() if link.expires_at else None,
        "url": f"/share/{link.hash}",
    }


@router.get("/share/{link_hash}", response_model=dict)
async def resolve_share_link(
    link_hash: str,
    password: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """Resolve a share link and return the underlying item metadata (no auth required)."""
    link = item_service.verify_share_link(db, link_hash, password)
    if not link:
        raise HTTPException(
            status_code=403,
            detail="Invalid, expired, or password-protected link",
        )
    return {
        "permission": link.permission,
        "item": _serialize_item(link.item),
    }


# ---------------------------------------------------------------------------
# File / Folder Creation
# ---------------------------------------------------------------------------


@router.post("/folders", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_folder(
    payload: schemas.FolderCreateRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Create a new empty folder."""
    user_id = int(user.id)  # type: ignore[arg-type]
    folder = item_service.create_folder(db, user_id, payload.name, payload.parent_id)
    return _serialize_item(folder)


@router.post("/files/text", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_text_file(
    payload: schemas.TextFileCreateRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Create a .txt file with the provided raw string content."""
    user_id = int(user.id)  # type: ignore[arg-type]
    file_item = item_service.create_text_file(
        db, user_id, payload.name, payload.content, payload.parent_id
    )
    return _serialize_item(file_item)


@router.post("/files/upload", response_model=dict, status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = File(...),
    parent_id: str | None = Query(None),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Upload a file via multipart form, extract metadata, and register it in CloudHub."""
    user_id = int(user.id)  # type: ignore[arg-type]

    content = await file.read()
    size = len(content)
    mime_type = file.content_type or "application/octet-stream"
    filename = file.filename or "upload"

    file_item = item_service.register_uploaded_file(
        db,
        user_id,
        name=filename,
        size=size,
        mime_type=mime_type,
        parent_id=parent_id,
    )
    return _serialize_item(file_item)


# ---------------------------------------------------------------------------
# Folder Size Sync (admin/repair utility)
# ---------------------------------------------------------------------------


@router.post("/{folder_id}/recalculate-size", response_model=dict)
async def recalculate_size(
    folder_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Recursively recompute and persist the size of a folder from its descendants.

    Use this as a repair utility; normal CRUD operations keep sizes in sync automatically.
    """
    folder = (
        db.query(models.FileSystemItem)
        .filter(
            models.FileSystemItem.id == folder_id,
            models.FileSystemItem.user_id == int(user.id),  # type: ignore[arg-type]
            models.FileSystemItem.is_folder == True,  # noqa: E712
        )
        .first()
    )
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    new_size = item_service.recalculate_folder_size(db, folder_id)
    return {"folder_id": folder_id, "size": new_size}


# ---------------------------------------------------------------------------
# Serialization helper
# ---------------------------------------------------------------------------


def _serialize_item(item: models.FileSystemItem) -> dict:
    """Convert a FileSystemItem ORM object to a JSON-serializable dict."""
    return {
        "id": item.id,
        "name": item.name,
        "is_folder": item.is_folder,
        "parent_id": item.parent_id,
        "provider": item.provider,
        "provider_id": item.provider_id,
        "mime_type": item.mime_type,
        "size": item.size,
        "extension": item.extension,
        "tags": [{"id": t.id, "name": t.name} for t in item.tags],
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }
