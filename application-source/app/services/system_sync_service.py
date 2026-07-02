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

from fastapi import HTTPException
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


def _adjust_folder_and_ancestors_no_commit(db: Session, folder_id: str, delta: int) -> None:
    """Adjust a folder's size and all its ancestors (including the folder) by delta.

    Used during sync for incremental size update    s without immediate commit.
    """
    if delta == 0:
        return

    current_id = folder_id
    while current_id:
        folder = (
            db.query(models.FileSystemItem).filter(models.FileSystemItem.id == current_id).first()
        )
        if not folder:
            break
        folder.size = max(0, (folder.size or 0) + delta)
        current_id = folder.parent_id
    # No commit - caller handles transaction commit at batch boundaries


async def full_system_sync(user_id: int) -> dict[str, Any]:
    """Run a full recursive synchronization for all linked accounts with rate limiting.

    This is the "deep sync" - expensive and limited to once per 6 hours per account.
    """
    logger.info("Starting full system sync (deep) for user %d", user_id)
    synced = []
    skipped = []

    try:
        with SessionLocal() as db:
            accounts = account_service.get_user_accounts(db, user_id)
            now = datetime.datetime.now(datetime.timezone.utc)

            for account in accounts:
                try:
                    # Check rate limit: skip if synced within last 6 hours
                    if (
                        account.last_full_sync
                        and (now - account.last_full_sync).total_seconds() < 6 * 3600
                    ):
                        logger.info(
                            "Skipping deep sync for %s: rate limited (last sync: %s)",
                            account.email,
                            account.last_full_sync,
                        )
                        skipped.append(
                            {
                                "email": account.email,
                                "provider": account.provider,
                                "reason": "rate_limited",
                                "retry_after_seconds": 6 * 3600,
                            }
                        )
                        continue

                    await _sync_account(db, user_id, account)

                    # Update last_full_sync timestamp
                    account.last_full_sync = now
                    db.commit()

                    synced.append({"email": account.email, "provider": account.provider})
                    logger.info("Deep sync completed for %s", account.email)
                except Exception:
                    logger.exception(
                        "Error syncing account %s (%s)", account.email, account.provider
                    )
                    db.rollback()  # Reset session before continuing with next account
                    skipped.append(
                        {"email": account.email, "provider": account.provider, "reason": "error"}
                    )

            logger.info(
                "Deep sync summary for user %d: %d synced, %d skipped",
                user_id,
                len(synced),
                len(skipped),
            )
            return {
                "message": f"Deep sync completed: {len(synced)} synced, {len(skipped)} skipped",
                "synced_accounts": synced,
                "skipped_accounts": skipped,
                "total_synced": len(synced),
                "total_skipped": len(skipped),
            }

    except Exception as e:
        logger.exception("Global error during full system sync for user %d: %s", user_id, e)
        raise


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
            # Track old size and parent for unified delta propagation
            old_size = existing_item.size or 0
            old_parent_id = existing_item.parent_id

            # Update item attributes
            existing_item.name = node["name"]
            existing_item.parent_id = parent_local_id
            existing_item.is_folder = node["is_folder"]
            existing_item.mime_type = node.get("mime_type")
            existing_item.size = new_size = node.get("size", 0)
            existing_item.extension = node.get("extension")
            existing_item.extra_metadata = node.get("extra_metadata")

            # Update dates if provided by cloud, else keep existing
            if node.get("created_at"):
                existing_item.created_at = node["created_at"]
            if node.get("updated_at"):
                existing_item.updated_at = node["updated_at"]

            # Unified size adjustment: subtract old_size from old parent chain,
            # add new_size to new parent chain

            # This handles both size changes (same parent, old!=new) and moves (different parent)
            new_parent_id = parent_local_id
            if old_parent_id != new_parent_id or old_size != new_size:
                if old_parent_id:
                    _adjust_folder_and_ancestors_no_commit(db, old_parent_id, -old_size)
                if new_parent_id:
                    _adjust_folder_and_ancestors_no_commit(db, new_parent_id, new_size)
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
                created_at=node.get("created_at") or datetime.datetime.now(datetime.timezone.utc),
                updated_at=node.get("updated_at") or datetime.datetime.now(datetime.timezone.utc),
            )
            db.add(new_item)
            db.flush()  # Ensure ID is available before propagation

            # Propagate size increment for new items: add to parent chain
            item_size = new_item.size or 0
            if item_size > 0 and new_item.parent_id:
                _adjust_folder_and_ancestors_no_commit(db, new_item.parent_id, item_size)

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

    # 5. Cleanup stale entries with delta tracking
    stale_items = [item for item in existing_items if item.provider_id not in seen_provider_ids]
    if stale_items:
        logger.info("Cleaning up %d stale items for %s", len(stale_items), account.provider)

        # Aggregate size deltas per parent before deletion
        parent_size_deltas: dict[str | None, int] = {}
        for item in stale_items:
            pid = item.parent_id
            size = item.size or 0
            if pid:
                parent_size_deltas[pid] = parent_size_deltas.get(pid, 0) - size

        # Delete in batches to prevent locking issues
        for i in range(0, len(stale_items), BATCH_SIZE):
            batch_stale = stale_items[i : i + BATCH_SIZE]
            for item in batch_stale:
                db.delete(item)
            db.commit()
            await asyncio.sleep(0.01)

        # Apply negative deltas to parent folders (non-committing, then commit)
        for parent_id, delta in parent_size_deltas.items():
            if parent_id and delta != 0:
                _adjust_folder_and_ancestors_no_commit(db, parent_id, delta)
        db.commit()  # Commit parent size updates after applying all deltas

    # 6. Enqueue thumbnails
    if media_to_enqueue:
        enqueued = 0
        skipped = 0
        # Using a background priority of 2 for sync-discovered files
        for media_file in media_to_enqueue:
            if await ThumbnailSyncManager.enqueue_thumbnail(user_id, "background", media_file):
                enqueued += 1
            else:
                skipped += 1

        logger.info(
            "Thumbnail enqueue summary during sync: candidates=%d enqueued=%d skipped=%d",
            len(media_to_enqueue),
            enqueued,
            skipped,
        )


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
                        ).replace(tzinfo=datetime.timezone.utc)
                    except ValueError:
                        pass
                if f.get("modifiedTime"):
                    try:
                        updated_at = datetime.datetime.strptime(
                            f["modifiedTime"], "%Y-%m-%dT%H:%M:%S.%fZ"
                        ).replace(tzinfo=datetime.timezone.utc)
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
                created_at = datetime.datetime.fromtimestamp(data["ts"], datetime.timezone.utc)
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
        is_folder_map = {}
        children_map = {}

        for item in items:
            sizes[item.id] = item.size or 0
            is_folder_map[item.id] = item.is_folder
            if item.parent_id:
                if item.parent_id not in children_map:
                    children_map[item.parent_id] = []
                children_map[item.parent_id].append(item.id)

        # Bottom-up calculation via post-order traversal using memoization
        calculated_folder_sizes: dict[str, int] = {}

        def get_size(item_id: str) -> int:
            if item_id in calculated_folder_sizes:
                return calculated_folder_sizes[item_id]

            # Only include file sizes; folders only sum their children
            total = 0 if is_folder_map.get(item_id, False) else sizes.get(item_id, 0)
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


def recalculate_all_folder_sizes(db: Session, user_id: int) -> None:
    """Public wrapper to recalculate all folder sizes for a user."""
    logger.info("Manual folder size recalculation requested for user %d", user_id)
    _recalculate_all_folder_sizes(db, user_id)


# ---------------------------------------------------------------------------
# Public Service API - New Granular Sync & Maintenance Functions
# ---------------------------------------------------------------------------


async def incremental_sync(user_id: int, account_id: int | None = None) -> dict[str, Any]:
    """Perform an incremental sync - update only changed items with delta propagation.

    This is lightweight and suitable for frequent use (e.g., folder refresh).

    Args:
        user_id: User performing the sync
        account_id: Optional specific account to sync; if None, syncs all accounts
    """
    logger.info(
        "Starting incremental sync for user %d (account_id=%s)", user_id, account_id or "all"
    )
    synced = []
    skipped = []

    try:
        with SessionLocal() as db:
            if account_id:
                account = (
                    db.query(models.Account)
                    .filter(models.Account.id == account_id, models.Account.user_id == user_id)
                    .first()
                )
                if not account:
                    raise HTTPException(status_code=404, detail="Account not found")
                accounts = [account]
            else:
                accounts = account_service.get_user_accounts(db, user_id)

            for account in accounts:
                try:
                    await _sync_account(db, user_id, account)
                    synced.append({"email": account.email, "provider": account.provider})
                    logger.info("Incremental sync completed for %s", account.email)
                except Exception as e:
                    logger.exception("Error in incremental sync for %s: %s", account.email, e)
                    db.rollback()  # Reset session for next account
                    skipped.append(
                        {"email": account.email, "provider": account.provider, "error": str(e)}
                    )

            return {
                "message": f"Incremental sync: {len(synced)} accounts updated",
                "synced_accounts": synced,
                "skipped_accounts": skipped,
                "total_synced": len(synced),
            }
    except Exception as e:
        logger.exception("Incremental sync failed for user %d: %s", user_id, e)
        raise


async def deep_sync(user_id: int, account_id: int | None = None) -> dict[str, Any]:
    """Perform a full deep sync with rate limiting (6 hours per account).

    Args:
        user_id: User performing the sync
        account_id: Optional specific account to sync; if None, syncs all non-rate-limited accounts

    Returns:
        dict with sync results and rate limit info
    """
    logger.info("Starting deep sync for user %d (account_id=%s)", user_id, account_id or "all")
    return await full_system_sync(user_id)  # full_system_sync already handles rate limiting


def maintenance_recalculate_stats(db: Session, user_id: int) -> dict[str, Any]:
    """Recalculate all folder sizes bottom-up - one-time recovery/repair operation."""
    logger.info("Maintenance: Recalculating statistics for user %d", user_id)
    try:
        recalculate_all_folder_sizes(db, user_id)
        return {
            "message": "Folder statistics recalculated successfully",
            "operation": "recalculate_stats",
        }
    except Exception as e:
        logger.exception("Maintenance recalc failed for user %d: %s", user_id, e)
        raise


async def maintenance_repair_thumbnails(user_id: int) -> dict[str, Any]:
    """Re-enqueue all media files (images/videos) for thumbnail regeneration.

    Useful when thumbnails are missing or corrupted system-wide.
    """
    logger.info("Maintenance: Repairing thumbnails for user %d", user_id)
    try:
        with SessionLocal() as db:
            # Fetch all non-folder items with common media extensions
            media_extensions = (
                ".mp4",
                ".mkv",
                ".mov",
                ".avi",
                ".wmv",
                ".flv",
                ".webm",
                ".jpg",
                ".jpeg",
                ".png",
                ".webp",
                ".heic",
                ".gif",
                ".bmp",
            )

            # Query all file items for the user
            items = (
                db.query(models.FileSystemItem)
                .filter(
                    models.FileSystemItem.user_id == user_id,
                    models.FileSystemItem.is_folder.is_(False),
                )
                .all()
            )

            queued = 0
            for item in items:
                if not item.extension:
                    continue
                ext = f".{item.extension.lower()}"
                if ext not in media_extensions:
                    continue

                # Build file_info dict in the format expected by ThumbnailSyncManager
                provider = item.provider
                file_id = item.provider_id or item.id

                file_info = {"ids": {provider: file_id}, "name": item.name, "type": "file"}

                await ThumbnailSyncManager.enqueue_thumbnail(user_id, "maintenance", file_info)
                queued += 1

            logger.info("Repair thumbnails: enqueued %d media files for user %d", queued, user_id)
            return {
                "message": f"Thumbnail repair enqueued {queued} media files",
                "queued_files": queued,
                "operation": "repair_thumbnails",
            }
    except Exception as e:
        logger.exception("Maintenance thumbnail repair failed for user %d: %s", user_id, e)
        raise
