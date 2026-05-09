"""Library Service Module.

Responsibilities:
- Coordinate file listing across multiple providers
- Merge and sort file lists into a unified view
- Inject watch history and metadata into file items

Boundaries:
- Does not handle raw API calls to providers (delegated to gdrive/mega services)
- Does not handle database session management
"""

import asyncio
import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.db import models
from app.services.gdrive_service import list_files as gdrive_list
from app.services.mega_service import get_mega_session, invalidate_session
from app.services.mega_service import list_files as mega_list  # type: ignore[import]
from app.utils.folder_merger import merge_files  # type: ignore[import]

logger = logging.getLogger(__name__)


async def list_all_files(
    db: Session, accounts: list[Any], folder_id: str, sync: bool = False
) -> list[dict[str, Any]]:
    """Fetch and merge file lists from all provided accounts for a given folder in parallel."""

    # Resolve folder mapping if it's a JSON string
    folder_map = {}
    if folder_id != "root":
        try:
            folder_map = json.loads(folder_id)
        except (json.JSONDecodeError, TypeError):
            pass

    async def fetch_account_files(
        acc: Any,
    ) -> tuple[Any, str | None, str | None, list[dict[str, Any]]]:
        # Resolve the specific folder ID for this provider
        raw_target_id = folder_map.get(acc.provider, folder_id)

        # If the ID is account-aware (email:id), check if it belongs to this account
        target_id = raw_target_id
        sync_parent_provider_id: str | None = raw_target_id

        # Handle list of IDs (merged folders)
        if isinstance(raw_target_id, list):
            # Find the ID in the list that belongs to this account
            target_id = None
            sync_parent_provider_id = None
            for rid in raw_target_id:
                if ":" in rid:
                    email_prefix, actual_id = rid.split(":", 1)
                    if email_prefix == acc.email:
                        target_id = actual_id
                        sync_parent_provider_id = rid
                        break

            if target_id is None:
                return acc, None, None, []

        # Handle single ID
        elif ":" in raw_target_id:
            email_prefix, actual_id = raw_target_id.split(":", 1)
            if email_prefix != acc.email:
                # This folder ID belongs to a different account of the same provider
                return acc, None, None, []
            target_id = actual_id
            sync_parent_provider_id = raw_target_id

        logger.info(
            "Fetching files for account %s (%s) in folder %s...",
            acc.email,
            acc.provider,
            target_id,
        )

        try:
            res = []
            if acc.provider == "gdrive":
                res = await asyncio.to_thread(gdrive_list, acc, None, target_id)
                logger.info("GDrive account %s returned %d files", acc.email, len(res))
            elif acc.provider == "mega":
                m = await asyncio.to_thread(get_mega_session, acc.access_token, acc.refresh_token)
                if m:
                    res = await asyncio.to_thread(mega_list, m, acc.email, target_id)
                    logger.info("MEGA account %s returned %d files", acc.email, len(res))
                else:
                    logger.warning("Failed to get MEGA session for %s", acc.email)

            return acc, target_id, sync_parent_provider_id, res
        except Exception:
            logger.exception("Error listing files for %s (%s)", acc.provider, acc.email)
            if acc.provider == "mega":
                await asyncio.to_thread(invalidate_session, acc.access_token)
            return acc, target_id, sync_parent_provider_id, []

    # Run all account fetches in parallel
    logger.info("Starting parallel fetch for %d accounts (sync=%s)", len(accounts), sync)
    results = await asyncio.gather(*(fetch_account_files(acc) for acc in accounts))

    # Sync is intentionally sequential and on the request thread to avoid
    # cross-thread SQLAlchemy Session usage and nested flush/commit collisions.
    if sync:
        from app.services import sync_service

        for acc, _target_id, sync_parent_provider_id, files in results:
            if not files:
                continue
            user_id = int(acc.user_id)  # type: ignore[arg-type]
            sync_service.sync_account_to_db(
                db, user_id, acc.provider, sync_parent_provider_id, files, str(acc.email)
            )

    # Filter out empty lists and merge
    all_file_lists = [f for _, _, _, f in results if f]
    logger.info("Merging %d non-empty file lists", len(all_file_lists))
    return merge_files(all_file_lists)  # type: ignore[arg-type,return-value]


def inject_metadata(db: Session, user_id: int, files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Augment file/folder items with persisted metadata, recursive sizes, and watch history."""

    all_ids: list[str] = []
    for f in files:
        for value in f["ids"].values():
            if isinstance(value, list):
                all_ids.extend(v for v in value if isinstance(v, str))
            elif isinstance(value, str):
                all_ids.append(value)

    # Fetch relevant metadata for files (thumbnails, dimensions, duration)
    persisted_metadata = {
        m.file_id: m
        for m in db.query(models.FileMetadata)
        .filter(models.FileMetadata.file_id.in_(all_ids))  # type: ignore[arg-type]
        .all()
    }

    # Fetch recursive sizes from the unified FileSystemItem table (calculated during sync)
    persisted_sizes = {
        item.provider_id: item.size
        for item in db.query(models.FileSystemItem)
        .filter(
            models.FileSystemItem.user_id == user_id,
            models.FileSystemItem.provider_id.in_(all_ids),
        )
        .all()
    }

    # Fetch watch history for authenticated users
    history_map = {}
    if user_id >= 0:
        history_records = (
            db.query(models.WatchHistory).filter(models.WatchHistory.user_id == user_id).all()
        )
        history_map = {h.file_id: h for h in history_records}

    for f in files:
        # Inject cached recursive size if available (for both files and folders)
        found_db_size = False
        total_db_size = 0
        for _, provider_value in f["ids"].items():
            provider_ids = provider_value if isinstance(provider_value, list) else [provider_value]
            for provider_id in provider_ids:
                if not isinstance(provider_id, str):
                    continue
                if provider_id in persisted_sizes:
                    db_size = persisted_sizes[provider_id]
                    if db_size is not None:
                        # For folders, use DB size only when it's positive.
                        # Zero often means not yet fully synced, so fallback cache should run.
                        if f["type"] == "folder":
                            if db_size > 0:
                                total_db_size += db_size
                                found_db_size = True
                        elif db_size > 0:
                            f["size"] = db_size
                            found_db_size = True
                            break
            if f["type"] == "file" and found_db_size:
                break

        if f["type"] == "folder" and found_db_size:
            f["size"] = total_db_size

        # Fallback: Calculate folder size from existing folder cache if not in unified DB
        if f["type"] == "folder" and not found_db_size:
            # The folder's 'id' in the merged view is a JSON string of its constituent IDs
            # However, we often use the stringified version as the cache key
            folder_key = json.dumps(f["ids"], sort_keys=True)
            f["size"] = calculate_folder_size_from_cache(db, user_id, folder_key)

        if f["type"] == "file":
            # Initialize defaults
            f.update(
                {
                    "progress_percentage": None,
                    "duration": None,
                    "current_time": None,
                    "width": None,
                    "height": None,
                    "updated_at": None,
                }
            )

            for _, file_id in f["ids"].items():
                if file_id in persisted_metadata:
                    m = persisted_metadata[file_id]
                    f["duration"] = m.duration
                    f["width"] = m.width
                    f["height"] = m.height
                    f["updated_at"] = m.updated_at

                # Signal if the file is currently being processed or in the queue
                from app.services.background_service import ThumbnailSyncManager

                if any(
                    ThumbnailSyncManager.is_task_active(file_id) for file_id in f["ids"].values()
                ):
                    f["is_generating"] = True
                else:
                    f["is_generating"] = False

                if file_id in history_map:
                    record = history_map[file_id]
                    f["current_time"] = record.current_time
                    if record.duration > 0:  # type: ignore[operator]
                        f["duration"] = record.duration
                        f["progress_percentage"] = min(
                            100,
                            int((record.current_time / record.duration) * 100),
                        )  # type: ignore[operator,arg-type]
                    break

    return files


def get_cached_folder(db: Session, user_id: int, folder_id: str) -> list[dict[str, Any]] | None:
    """Retrieve folder listing from database cache."""

    cache = (
        db.query(models.FolderCache)
        .filter(
            models.FolderCache.user_id == user_id,
            models.FolderCache.folder_id == folder_id,
        )
        .first()
    )
    return cache.data if cache else None  # type: ignore[return-value]


def save_folder_cache(
    db: Session, user_id: int, folder_id: str, data: list[dict[str, Any]]
) -> None:
    """Persist folder listing to database cache."""

    cache = (
        db.query(models.FolderCache)
        .filter(
            models.FolderCache.user_id == user_id,
            models.FolderCache.folder_id == folder_id,
        )
        .first()
    )

    if cache:
        cache.data = data
    else:
        cache = models.FolderCache(user_id=user_id, folder_id=folder_id, data=data)
        db.add(cache)

    db.commit()


def calculate_folder_size_from_cache(db: Session, user_id: int, folder_id: str) -> int:
    """Recursively calculate folder size using available folder_cache entries.

    This provides 'just-in-time' calculation for folders the user has visited,
    even if a full global sync hasn't run yet.
    """
    cache_data = get_cached_folder(db, user_id, folder_id)
    if not cache_data:
        return 0

    total = 0
    for item in cache_data:
        if item["type"] == "file":
            total += item.get("size", 0)
        elif item["type"] == "folder":
            # If the folder has its own cache entry, recurse
            sub_folder_id = json.dumps(item["ids"], sort_keys=True)
            total += calculate_folder_size_from_cache(db, user_id, sub_folder_id)

    return total
