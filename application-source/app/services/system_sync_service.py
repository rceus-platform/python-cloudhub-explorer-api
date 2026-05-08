"""System Synchronization Service.

Responsibilities:
- Perform full recursive synchronization of all cloud providers for a user.
- Build the unified FileSystemItem tree.
- Maintain folder sizes bottom-up.
- Trigger thumbnail background generation.
- Manage memory usage with batching.
"""

import asyncio
import datetime
import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.db import models
from app.db.session import SessionLocal
from app.services import account_service
from app.services.background_service import ThumbnailSyncManager
from app.services.gdrive_service import get_drive_service, get_valid_credentials
from app.services.mega_service import get_mega_session
from app.utils.file_utils import get_media_type

logger = logging.getLogger(__name__)

BATCH_SIZE = 1000


async def full_system_sync(user_id: int) -> None:
    """Run a full recursive synchronization for all linked accounts of a user."""
    logger.info("Starting full system sync for user %d", user_id)
    try:
        with SessionLocal() as db:
            accounts = account_service.get_user_accounts(db, user_id)

            for account in accounts:
                try:
                    await _sync_account(db, user_id, account)
                except Exception:
                    logger.exception(
                        "Error syncing account %s (%s)", account.email, account.provider
                    )

            # Recalculate all folder sizes bottom-up after all accounts are synced
            logger.info("Recalculating folder sizes for user %d...", user_id)
            _recalculate_all_folder_sizes(db, user_id)
            logger.info("Full system sync completed for user %d", user_id)

    except Exception:
        logger.exception("Global error during full system sync for user %d", user_id)


async def _sync_account(db: Session, user_id: int, account: models.Account) -> None:
    """Sync a single account's entire file tree."""
    logger.info("Syncing account %s (%s)", account.email, account.provider)

    # 1. Load existing items for this account to minimize DB queries during mapping
    existing_items = (
        db.query(models.FileSystemItem)
        .filter(
            models.FileSystemItem.user_id == user_id,
            models.FileSystemItem.provider == account.provider,
        )
        .all()
    )

    existing_map = {item.provider_id: item for item in existing_items if item.provider_id}
    # To map provider parent IDs to local UUIDs
    id_mapping = {item.provider_id: item.id for item in existing_items if item.provider_id}
    seen_provider_ids = set()
    media_to_enqueue = []

    # 2. Fetch all cloud nodes
    if account.provider == "gdrive":
        nodes = await asyncio.to_thread(_fetch_gdrive_nodes, account, db)
    elif account.provider == "mega":
        nodes = await asyncio.to_thread(_fetch_mega_nodes, account)
    else:
        logger.warning("Unknown provider %s", account.provider)
        return

    # 3. First pass: Assign UUIDs for everything to ensure parent mapping works
    for node in nodes:
        pid = node["provider_id"]
        if pid not in id_mapping:
            id_mapping[pid] = str(uuid.uuid4())

    # 4. Second pass: Build ORM objects and batch insert/update
    logger.info("Processing %d nodes for %s", len(nodes), account.provider)

    batch_count = 0
    for node in nodes:
        pid = node["provider_id"]
        seen_provider_ids.add(pid)
        local_id = id_mapping[pid]

        # Resolve parent local UUID
        parent_provider_id = node.get("parent_provider_id")
        parent_local_id = id_mapping.get(parent_provider_id) if parent_provider_id else None

        existing_item = existing_map.get(pid)

        if existing_item:
            # Update
            existing_item.name = node["name"]
            existing_item.parent_id = parent_local_id
            existing_item.is_folder = node["is_folder"]
            existing_item.mime_type = node.get("mime_type")
            existing_item.size = node.get("size", 0)
            existing_item.extension = node.get("extension")
            existing_item.extra_metadata = node.get("extra_metadata")

            # Update dates if provided by cloud, else keep existing
            if node.get("created_at"):
                existing_item.created_at = node["created_at"]
            if node.get("updated_at"):
                existing_item.updated_at = node["updated_at"]
        else:
            # Insert
            new_item = models.FileSystemItem(
                id=local_id,
                provider_id=pid,
                provider=account.provider,
                user_id=user_id,
                name=node["name"],
                parent_id=parent_local_id,
                is_folder=node["is_folder"],
                mime_type=node.get("mime_type"),
                size=node.get("size", 0),
                extension=node.get("extension"),
                extra_metadata=node.get("extra_metadata"),
                created_at=node.get("created_at") or datetime.datetime.utcnow(),
                updated_at=node.get("updated_at") or datetime.datetime.utcnow(),
            )
            db.add(new_item)

        # Check if it's a media file for thumbnail generation
        if not node["is_folder"]:
            media_type = get_media_type(node["name"])
            if media_type and (media_type.startswith("image/") or media_type.startswith("video/")):
                media_to_enqueue.append(
                    {"ids": {account.provider: pid}, "name": node["name"], "type": "file"}
                )

        batch_count += 1
        if batch_count >= BATCH_SIZE:
            db.commit()
            batch_count = 0
            # Yield to event loop to prevent event loop blocking
            await asyncio.sleep(0.01)

    if batch_count > 0:
        db.commit()

    # 5. Cleanup stale entries
    stale_items = [item for item in existing_items if item.provider_id not in seen_provider_ids]
    if stale_items:
        logger.info("Cleaning up %d stale items for %s", len(stale_items), account.provider)
        # Delete in batches to prevent locking issues
        for i in range(0, len(stale_items), BATCH_SIZE):
            batch_stale = stale_items[i : i + BATCH_SIZE]
            for item in batch_stale:
                db.delete(item)
            db.commit()
            await asyncio.sleep(0.01)

    # 6. Enqueue thumbnails
    if media_to_enqueue:
        logger.info("Enqueuing %d media files for thumbnail generation", len(media_to_enqueue))
        # Using a background priority of 2 for sync-discovered files
        for media_file in media_to_enqueue:
            await ThumbnailSyncManager.enqueue_thumbnail(user_id, "background", media_file)


def _fetch_gdrive_nodes(account: models.Account, db: Session) -> list[dict[str, Any]]:
    """Fetch all files and folders recursively from Google Drive."""
    creds = get_valid_credentials(account, db)
    if not creds:
        return []

    service = get_drive_service(creds)
    query = "trashed=false"
    nodes = []
    page_token = None

    while True:
        try:
            results = (
                service.files()
                .list(
                    q=query,
                    pageSize=1000,
                    fields=(
                        "nextPageToken, files(id, name, mimeType, size, parents, "
                        "fileExtension, createdTime, modifiedTime, thumbnailLink, "
                        "imageMediaMetadata, videoMediaMetadata)"
                    ),
                    pageToken=page_token,
                )
                .execute()
            )

            files = results.get("files", [])
            for f in files:
                is_folder = "folder" in f.get("mimeType", "")

                # Google Drive items can have multiple parents, we pick the first one
                parent_id = f.get("parents", [None])[0]

                # Parse times
                created_at = None
                updated_at = None
                if f.get("createdTime"):
                    try:
                        # e.g., '2023-01-01T12:00:00.000Z'
                        created_at = datetime.datetime.strptime(
                            f["createdTime"], "%Y-%m-%dT%H:%M:%S.%fZ"
                        )
                    except ValueError:
                        pass
                if f.get("modifiedTime"):
                    try:
                        updated_at = datetime.datetime.strptime(
                            f["modifiedTime"], "%Y-%m-%dT%H:%M:%S.%fZ"
                        )
                    except ValueError:
                        pass

                node = {
                    "provider_id": f["id"],
                    "name": f.get("name", "Unknown"),
                    "parent_provider_id": parent_id,
                    "is_folder": is_folder,
                    "mime_type": f.get("mimeType"),
                    "size": int(f.get("size", 0)) if not is_folder else 0,
                    "extension": f.get("fileExtension"),
                    "extra_metadata": {
                        "thumbnailLink": f.get("thumbnailLink"),
                        "imageMediaMetadata": f.get("imageMediaMetadata"),
                        "videoMediaMetadata": f.get("videoMediaMetadata"),
                    },
                    "created_at": created_at,
                    "updated_at": updated_at,
                }
                nodes.append(node)

            page_token = results.get("nextPageToken")
            if not page_token:
                break
        except Exception as e:
            logger.error("GDrive fetch error for %s: %s", account.email, e)
            break

    return nodes


def _fetch_mega_nodes(account: models.Account) -> list[dict[str, Any]]:
    """Fetch all files and folders recursively from MEGA."""
    m = get_mega_session(account.access_token, account.refresh_token)
    if not m:
        return []

    try:
        mega_files = m.get_files()
    except Exception as e:
        logger.error("MEGA fetch error for %s: %s", account.email, e)
        return []

    if not mega_files:
        return []

    nodes = []
    # Identify root folder to skip mapping it as a normal item, or map it properly
    # MEGA root is usually type 2
    root_id = None
    for fid, data in mega_files.items():
        if data.get("t") == 2:
            root_id = fid
            break

    for fid, data in mega_files.items():
        t = data.get("t")
        # Skip special nodes except if we want to represent root as a folder
        # For our system, cloud roots are just items with parent_id = None
        if t in [3, 4]:  # Inbox, Trash
            continue

        is_folder = t in [1, 2]  # 1=Folder, 2=Root
        parent_id = data.get("p")

        # If it's the MEGA root, it has no parent in our system
        if fid == root_id or t == 2:
            parent_id = None
            name = "MEGA Root"
        else:
            name = data.get("a", {}).get("n", "Unknown")

        # If parent is root, we map it to None to be at the top level of the provider
        if parent_id == root_id:
            parent_id = None

        created_at = None
        if data.get("ts"):
            try:
                created_at = datetime.datetime.utcfromtimestamp(data["ts"])
            except Exception:
                pass

        ext = None
        if not is_folder and "." in name:
            ext = name.split(".")[-1].lower()

        prefixed_fid = f"{account.email}:{fid}"
        prefixed_parent_id = f"{account.email}:{parent_id}" if parent_id else None

        node = {
            "provider_id": prefixed_fid,
            "name": name,
            "parent_provider_id": prefixed_parent_id,
            "is_folder": is_folder,
            "mime_type": None,  # MEGA doesn't provide mime types directly
            "size": data.get("s", 0) if not is_folder else 0,
            "extension": ext,
            "extra_metadata": {"t": t},
            "created_at": created_at,
            "updated_at": created_at,  # MEGA mostly provides one timestamp
        }
        nodes.append(node)

    return nodes


def _recalculate_all_folder_sizes(db: Session, user_id: int) -> None:
    """
    Industry Standard Post-Sync Processing:
    Recalculate folder sizes bottom-up for all folders owned by the user.
    This avoids massive recursion overhead during the tree building phase.
    """
    try:
        # Reset all folder sizes to 0 first
        db.query(models.FileSystemItem).filter(
            models.FileSystemItem.user_id == user_id, models.FileSystemItem.is_folder
        ).update({models.FileSystemItem.size: 0}, synchronize_session=False)
        db.commit()

        # Build a memory representation of the tree to calculate sizes
        # We only need: id, parent_id, size, is_folder
        items = (
            db.query(
                models.FileSystemItem.id,
                models.FileSystemItem.parent_id,
                models.FileSystemItem.size,
                models.FileSystemItem.is_folder,
            )
            .filter(models.FileSystemItem.user_id == user_id)
            .all()
        )

        sizes = {}
        children_map = {}

        for item in items:
            sizes[item.id] = item.size or 0
            if item.parent_id:
                if item.parent_id not in children_map:
                    children_map[item.parent_id] = []
                children_map[item.parent_id].append(item.id)

        # Bottom-up calculation via post-order traversal using memoization
        calculated_folder_sizes = {}

        def get_size(item_id):
            if item_id in calculated_folder_sizes:
                return calculated_folder_sizes[item_id]

            total = sizes.get(item_id, 0)
            if item_id in children_map:
                for child_id in children_map[item_id]:
                    total += get_size(child_id)

            calculated_folder_sizes[item_id] = total
            return total

        # Calculate for all roots
        for item in items:
            if item.is_folder:
                get_size(item.id)

        # Batch update database with calculated sizes
        update_mappings = [
            {"id": f_id, "size": size} for f_id, size in calculated_folder_sizes.items() if size > 0
        ]

        if update_mappings:
            # SQLAlchemy bulk update mappings
            # We chunk it to avoid giant queries
            for i in range(0, len(update_mappings), BATCH_SIZE):
                batch = update_mappings[i : i + BATCH_SIZE]
                db.bulk_update_mappings(models.FileSystemItem, batch)
            db.commit()

    except Exception as e:
        logger.error("Error recalculating folder sizes for user %d: %s", user_id, e)
        db.rollback()
