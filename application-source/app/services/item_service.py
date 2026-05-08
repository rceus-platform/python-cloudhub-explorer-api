"""Item Service Module.

Responsibilities:
- Implement CRUD operations for FileSystemItems (move, copy, rename, delete)
- Manage recursive folder size updates after any structural change
- Handle deep copy logic (DB records + physical storage trigger)
- Provide tag management (upsert, assign, remove)
- Generate and manage share links

Boundaries:
- Does not handle HTTP request/response concerns (delegated to API routes)
- Physical storage operations are delegated to the Node.js microservice
"""

import logging
import os
import secrets
import uuid
from datetime import datetime

import bcrypt
import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import models

logger = logging.getLogger(__name__)

# URL for the Node.js microservice handling physical file operations
NODE_SERVICE_URL = os.getenv("NODE_SERVICE_URL", "http://localhost:4000")


# ---------------------------------------------------------------------------
# Folder Size Helpers
# ---------------------------------------------------------------------------


def _propagate_size_change(db: Session, item_id: str, size_delta: int) -> None:
    """Walk up the parent chain and adjust each ancestor's cached size.

    This is the industry-standard "eager update" approach: it keeps folder
    sizes in sync without expensive on-read recursive queries.
    """
    item = db.query(models.FileSystemItem).filter(models.FileSystemItem.id == item_id).first()
    if not item or not item.parent_id:
        return

    current_id = item.parent_id
    while current_id:
        parent = (
            db.query(models.FileSystemItem)
            .filter(models.FileSystemItem.id == current_id)
            .first()
        )
        if not parent:
            break
        parent.size = (parent.size or 0) + size_delta  # type: ignore[assignment]
        current_id = parent.parent_id

    db.commit()


def recalculate_folder_size(db: Session, folder_id: str) -> int:
    """Recursively compute the true size of a folder from its immediate children.

    This uses an 'eager' approach: it trusts the cached 'size' field of child
    folders (which are kept in sync during their own sync/CRUD operations).
    """
    total: int = (
        db.query(func.sum(models.FileSystemItem.size))
        .filter(models.FileSystemItem.parent_id == folder_id)
        .scalar()
        or 0
    )

    # Update the folder itself
    db.query(models.FileSystemItem).filter(models.FileSystemItem.id == folder_id).update(
        {models.FileSystemItem.size: total}
    )
    db.commit()
    return total


# ---------------------------------------------------------------------------
# Move
# ---------------------------------------------------------------------------


async def move_items(
    db: Session, user_id: int, item_ids: list[str], destination_id: str | None
) -> list[models.FileSystemItem]:
    """Move items to a new parent folder and propagate size changes.

    Args:
        destination_id: Target folder UUID, or None to move to virtual root.
    """
    moved: list[models.FileSystemItem] = []
    for item_id in item_ids:
        item = (
            db.query(models.FileSystemItem)
            .filter(
                models.FileSystemItem.id == item_id,
                models.FileSystemItem.user_id == user_id,
            )
            .first()
        )
        if not item:
            logger.warning("Item %s not found for user %d during move", item_id, user_id)
            continue

        old_size = item.size or 0

        # Remove size from old parent chain
        if item.parent_id:
            _propagate_size_change(db, item_id, -(old_size))

        item.parent_id = destination_id  # type: ignore[assignment]

        # Add size to new parent chain
        if destination_id:
            _propagate_size_change(db, item_id, old_size)

        moved.append(item)

    db.commit()

    # Inform Node.js service about the physical move (fire-and-forget)
    if item_ids:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"{NODE_SERVICE_URL}/storage/move",
                    json={"item_ids": item_ids, "destination_id": destination_id},
                    headers=_internal_headers(),
                )
        except Exception:
            logger.warning("Node service /storage/move call failed (non-fatal)", exc_info=True)

    return moved


# ---------------------------------------------------------------------------
# Copy (Deep)
# ---------------------------------------------------------------------------


def _deep_copy_item(
    db: Session,
    user_id: int,
    item: models.FileSystemItem,
    destination_id: str | None,
    same_folder: bool,
) -> models.FileSystemItem:
    """Recursively duplicate a file or folder and all its descendants."""
    new_name = item.name
    if same_folder:
        # Only append _copy to the immediate item, not all descendants
        base, _, ext = item.name.rpartition(".")
        new_name = f"{base}_copy.{ext}" if ext else f"{item.name}_copy"

    new_item = models.FileSystemItem(
        id=str(uuid.uuid4()),
        provider_id=item.provider_id,  # same cloud object, new DB record
        provider=item.provider,
        user_id=user_id,
        name=new_name,
        parent_id=destination_id,
        is_folder=item.is_folder,
        mime_type=item.mime_type,
        size=item.size,
        extension=item.extension,
        extra_metadata=item.extra_metadata,
    )
    db.add(new_item)
    db.flush()  # obtain the new ID before recursing

    if item.is_folder:
        children = (
            db.query(models.FileSystemItem)
            .filter(models.FileSystemItem.parent_id == item.id)
            .all()
        )
        for child in children:
            _deep_copy_item(db, user_id, child, new_item.id, same_folder=False)

    return new_item


async def copy_items(
    db: Session, user_id: int, item_ids: list[str], destination_id: str | None
) -> list[models.FileSystemItem]:
    """Deep-copy items to a destination folder."""
    copied: list[models.FileSystemItem] = []
    for item_id in item_ids:
        item = (
            db.query(models.FileSystemItem)
            .filter(
                models.FileSystemItem.id == item_id,
                models.FileSystemItem.user_id == user_id,
            )
            .first()
        )
        if not item:
            continue

        same_folder = (item.parent_id == destination_id) or (
            item.parent_id is None and destination_id is None
        )
        new_item = _deep_copy_item(db, user_id, item, destination_id, same_folder)
        copied.append(new_item)

        if destination_id:
            _propagate_size_change(db, new_item.id, new_item.size or 0)

    db.commit()

    # Trigger physical copy on the Node.js service (fire-and-forget)
    if item_ids:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"{NODE_SERVICE_URL}/storage/copy",
                    json={
                        "item_ids": item_ids,
                        "destination_id": destination_id,
                        "copied_ids": [i.id for i in copied],
                    },
                    headers=_internal_headers(),
                )
        except Exception:
            logger.warning("Node service /storage/copy call failed (non-fatal)", exc_info=True)

    return copied


# ---------------------------------------------------------------------------
# Rename
# ---------------------------------------------------------------------------


def rename_item(db: Session, user_id: int, item_id: str, new_name: str) -> models.FileSystemItem:
    """Rename a file or folder record."""
    item = (
        db.query(models.FileSystemItem)
        .filter(
            models.FileSystemItem.id == item_id,
            models.FileSystemItem.user_id == user_id,
        )
        .first()
    )
    if not item:
        raise ValueError(f"Item {item_id} not found")

    item.name = new_name  # type: ignore[assignment]
    db.commit()
    db.refresh(item)
    return item


# ---------------------------------------------------------------------------
# Delete (Bulk)
# ---------------------------------------------------------------------------


async def delete_items(db: Session, user_id: int, item_ids: list[str]) -> list[str]:
    """Delete items from the DB and trigger physical removal on the Node.js service."""
    deleted_ids: list[str] = []
    size_deltas: dict[str | None, int] = {}  # parent_id -> cumulative size removed

    for item_id in item_ids:
        item = (
            db.query(models.FileSystemItem)
            .filter(
                models.FileSystemItem.id == item_id,
                models.FileSystemItem.user_id == user_id,
            )
            .first()
        )
        if not item:
            continue

        pid = item.parent_id
        size_deltas[pid] = size_deltas.get(pid, 0) + (item.size or 0)

        db.delete(item)
        deleted_ids.append(item_id)

    db.commit()

    # Update parent sizes after deletion
    for parent_id, delta in size_deltas.items():
        if parent_id and delta > 0:
            # Fabricate a minimal item to reuse _propagate_size_change
            _adjust_ancestor_sizes(db, parent_id, -delta)

    # Trigger physical deletion on the Node.js service (fire-and-forget)
    if deleted_ids:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"{NODE_SERVICE_URL}/storage/delete",
                    json={"item_ids": deleted_ids},
                    headers=_internal_headers(),
                )
        except Exception:
            logger.warning("Node service /storage/delete call failed (non-fatal)", exc_info=True)

    return deleted_ids


def _adjust_ancestor_sizes(db: Session, start_id: str, delta: int) -> None:
    """Walk up from start_id (which IS the folder) and adjust sizes."""
    current_id: str | None = start_id
    while current_id:
        folder = (
            db.query(models.FileSystemItem)
            .filter(models.FileSystemItem.id == current_id)
            .first()
        )
        if not folder:
            break
        folder.size = max(0, (folder.size or 0) + delta)  # type: ignore[assignment]
        current_id = folder.parent_id

    db.commit()


# ---------------------------------------------------------------------------
# Tag Management
# ---------------------------------------------------------------------------


def set_item_tags(
    db: Session, user_id: int, item_id: str, tag_names: list[str]
) -> models.FileSystemItem:
    """Replace the tag set on an item (upsert tags, remove old associations)."""
    item = (
        db.query(models.FileSystemItem)
        .filter(
            models.FileSystemItem.id == item_id,
            models.FileSystemItem.user_id == user_id,
        )
        .first()
    )
    if not item:
        raise ValueError(f"Item {item_id} not found")

    resolved_tags: list[models.Tag] = []
    for name in tag_names:
        name = name.strip().lower()
        if not name:
            continue
        tag = (
            db.query(models.Tag)
            .filter(models.Tag.user_id == user_id, models.Tag.name == name)
            .first()
        )
        if not tag:
            tag = models.Tag(user_id=user_id, name=name)
            db.add(tag)
            db.flush()
        resolved_tags.append(tag)

    item.tags = resolved_tags  # type: ignore[assignment]
    db.commit()
    db.refresh(item)
    return item


# ---------------------------------------------------------------------------
# Share Links
# ---------------------------------------------------------------------------


def create_share_link(
    db: Session,
    user_id: int,
    item_id: str,
    permission: str = "view",
    expires_at: datetime | None = None,
    password: str | None = None,
) -> models.ShareLink:
    """Create a unique, optionally password-protected share link."""
    item = (
        db.query(models.FileSystemItem)
        .filter(
            models.FileSystemItem.id == item_id,
            models.FileSystemItem.user_id == user_id,
        )
        .first()
    )
    if not item:
        raise ValueError(f"Item {item_id} not found")

    # Generate a 32-byte URL-safe token
    raw_hash = secrets.token_urlsafe(32)

    password_hash: str | None = None
    if password:
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    link = models.ShareLink(
        hash=raw_hash,
        item_id=item_id,
        created_by=user_id,
        permission=permission,
        expires_at=expires_at,
        password_hash=password_hash,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


def verify_share_link(
    db: Session, link_hash: str, password: str | None = None
) -> models.ShareLink | None:
    """Verify a share link is valid (not expired, correct password if set)."""
    link = (
        db.query(models.ShareLink)
        .filter(models.ShareLink.hash == link_hash)
        .first()
    )
    if not link:
        return None

    # Check expiry
    if link.expires_at and datetime.utcnow() > link.expires_at:  # type: ignore[operator]
        return None

    # Check password
    if link.password_hash:
        if not password:
            return None
        if not bcrypt.checkpw(
            password.encode(), link.password_hash.encode()  # type: ignore[arg-type]
        ):
            return None

    return link


# ---------------------------------------------------------------------------
# File/Folder Creation
# ---------------------------------------------------------------------------


def create_folder(
    db: Session, user_id: int, name: str, parent_id: str | None, provider: str = "local"
) -> models.FileSystemItem:
    """Initialize a new empty folder record in the database."""
    folder = models.FileSystemItem(
        id=str(uuid.uuid4()),
        name=name,
        parent_id=parent_id,
        is_folder=True,
        provider=provider,
        user_id=user_id,
        size=0,
    )
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return folder


def create_text_file(
    db: Session,
    user_id: int,
    name: str,
    content: str,
    parent_id: str | None,
    provider: str = "local",
) -> models.FileSystemItem:
    """Create a plain-text file record and store content size."""
    size = len(content.encode("utf-8"))
    file_item = models.FileSystemItem(
        id=str(uuid.uuid4()),
        name=name if name.endswith(".txt") else f"{name}.txt",
        parent_id=parent_id,
        is_folder=False,
        provider=provider,
        user_id=user_id,
        mime_type="text/plain",
        extension="txt",
        size=size,
        extra_metadata={"content": content},
    )
    db.add(file_item)
    db.flush()

    if parent_id:
        _propagate_size_change(db, file_item.id, size)

    db.commit()
    db.refresh(file_item)
    return file_item


def register_uploaded_file(
    db: Session,
    user_id: int,
    name: str,
    size: int,
    mime_type: str,
    parent_id: str | None,
    provider: str = "local",
    provider_id: str | None = None,
) -> models.FileSystemItem:
    """Register an already-uploaded file in the database with its metadata."""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    file_item = models.FileSystemItem(
        id=str(uuid.uuid4()),
        name=name,
        parent_id=parent_id,
        is_folder=False,
        provider=provider,
        user_id=user_id,
        mime_type=mime_type,
        extension=ext or None,
        size=size,
        provider_id=provider_id,
    )
    db.add(file_item)
    db.flush()

    if parent_id:
        _propagate_size_change(db, file_item.id, size)

    db.commit()
    db.refresh(file_item)
    return file_item


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _internal_headers() -> dict[str, str]:
    """Return headers for authenticated internal service calls."""
    headers: dict[str, str] = {}
    if settings.INTERNAL_SECRET:
        headers["X-Internal-Secret"] = settings.INTERNAL_SECRET
    return headers
