"""Sync Service Module.

Responsibilities:
- Synchronize cloud file structures into the local FileSystemItem database.
- Calculate and persist folder sizes during manual or background refresh.
- Maintain parent-child relationships between cloud objects in the DB.
"""

import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.db import models
from app.services.item_service import recalculate_folder_size

logger = logging.getLogger(__name__)


def sync_account_to_db(
    db: Session,
    user_id: int,
    provider: str,
    parent_provider_id: str | None,
    files: list[dict[str, Any]],
) -> None:
    """Synchronize a single account's files into the DB.

    Args:
        provider: 'gdrive' or 'mega'
        parent_provider_id: The cloud ID of the parent folder for this provider.
        files: The list of items fetched from this provider.
    """
    logger.info(
        "Syncing provider %s (parent: %s) to DB for user %d...",
        provider,
        parent_provider_id,
        user_id,
    )

    # 1. Resolve parent UUID in DB
    parent_uuid = None
    if parent_provider_id and parent_provider_id != "root":
        parent_record = (
            db.query(models.FileSystemItem)
            .filter(
                models.FileSystemItem.user_id == user_id,
                models.FileSystemItem.provider == provider,
                models.FileSystemItem.provider_id == parent_provider_id,
            )
            .first()
        )
        if parent_record:
            parent_uuid = parent_record.id
        else:
            # If parent not found, we might need to create a placeholder or just skip cleanup
            logger.warning("Parent folder %s not found in DB for %s", parent_provider_id, provider)

    # 2. Cleanup deleted items for this provider and parent
    cloud_provider_ids = {f.get("id") or f.get("ids", {}).get(provider) for f in files}
    cloud_provider_ids = {pid for pid in cloud_provider_ids if pid}

    db_items = (
        db.query(models.FileSystemItem)
        .filter(
            models.FileSystemItem.user_id == user_id,
            models.FileSystemItem.provider == provider,
            models.FileSystemItem.parent_id == parent_uuid,
        )
        .all()
    )
    for db_item in db_items:
        if db_item.provider_id not in cloud_provider_ids:
            logger.info("Removing deleted item %s (%s) from DB", db_item.name, db_item.id)
            db.delete(db_item)

    # 3. Upsert items
    updated_folders: set[str] = set()

    for f in files:
        p_id = f.get("id") or f.get("ids", {}).get(provider)
        if not p_id:
            continue

        item = (
            db.query(models.FileSystemItem)
            .filter(
                models.FileSystemItem.user_id == user_id,
                models.FileSystemItem.provider == provider,
                models.FileSystemItem.provider_id == p_id,
            )
            .first()
        )

        is_folder = f["type"] == "folder"
        size = f.get("size", 0)

        if item:
            item.name = f["name"]
            item.size = size
            item.parent_id = parent_uuid
            if is_folder:
                updated_folders.add(item.id)
        else:
            item = models.FileSystemItem(
                id=str(uuid.uuid4()),
                provider_id=p_id,
                provider=provider,
                user_id=user_id,
                name=f["name"],
                is_folder=is_folder,
                size=size,
                parent_id=parent_uuid,
            )
            db.add(item)
            db.flush()
            if is_folder:
                updated_folders.add(item.id)

    db.commit()

    # 4. Recalculate parent size
    if parent_uuid:
        recalculate_folder_size(db, parent_uuid)

    logger.info("Sync complete for %s. Updated %d folders.", provider, len(updated_folders))
