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


async def list_all_files(db: Session, accounts: list[Any], folder_id: str) -> list[dict[str, Any]]:
    """Fetch and merge file lists from all provided accounts for a given folder in parallel."""

    # Resolve folder mapping if it's a JSON string
    folder_map = {}
    if folder_id != "root":
        try:
            folder_map = json.loads(folder_id)
        except (json.JSONDecodeError, TypeError):
            pass

    async def fetch_account_files(acc: Any) -> list[dict[str, Any]]:
        # Resolve the specific folder ID for this provider
        raw_target_id = folder_map.get(acc.provider, folder_id)

        # If the ID is account-aware (email:id), check if it belongs to this account
        target_id = raw_target_id

        # Handle list of IDs (merged folders)
        if isinstance(raw_target_id, list):
            # Find the ID in the list that belongs to this account
            target_id = None
            for rid in raw_target_id:
                if ":" in rid:
                    email_prefix, actual_id = rid.split(":", 1)
                    if email_prefix == acc.email:
                        target_id = actual_id
                        break

            if target_id is None:
                return []

        # Handle single ID
        elif ":" in raw_target_id:
            email_prefix, actual_id = raw_target_id.split(":", 1)
            if email_prefix != acc.email:
                # This folder ID belongs to a different account of the same provider
                return []
            target_id = actual_id

        logger.info(
            "Fetching files for account %s (%s) in folder %s...",
            acc.email,
            acc.provider,
            target_id,
        )

        try:
            if acc.provider == "gdrive":
                res = await asyncio.to_thread(gdrive_list, acc, db, target_id)
                logger.info("GDrive account %s returned %d files", acc.email, len(res))
                return res
            elif acc.provider == "mega":
                m = await asyncio.to_thread(get_mega_session, acc.access_token, acc.refresh_token)
                if m:
                    res = await asyncio.to_thread(mega_list, m, acc.email, target_id)
                    logger.info("MEGA account %s returned %d files", acc.email, len(res))
                    return res
                else:
                    logger.warning("Failed to get MEGA session for %s", acc.email)
            return []
        except Exception:
            logger.exception("Error listing files for %s (%s)", acc.provider, acc.email)
            if acc.provider == "mega":
                await asyncio.to_thread(invalidate_session, acc.access_token)
            return []

    # Run all account fetches in parallel
    logger.info("Starting parallel fetch for %d accounts", len(accounts))
    results = await asyncio.gather(*(fetch_account_files(acc) for acc in accounts))

    # Filter out empty lists and merge
    all_file_lists = [f for f in results if f]
    logger.info("Merging %d non-empty file lists", len(all_file_lists))
    return merge_files(all_file_lists)  # type: ignore[arg-type,return-value]


def inject_metadata(db: Session, user_id: int, files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Augment file items with persisted metadata and user watch history."""

    all_ids = []
    for f in files:
        if f["type"] == "file":
            all_ids.extend(f["ids"].values())  # type: ignore[index,union-attr]

    # Fetch all relevant metadata in one query
    persisted_metadata = {
        m.file_id: m
        for m in db.query(models.FileMetadata)
        .filter(models.FileMetadata.file_id.in_(all_ids))  # type: ignore[arg-type]
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
        if f["type"] == "file":
            # Initialize defaults
            f.update(
                {
                    "progress_percentage": None,
                    "duration": None,
                    "current_time": None,
                    "width": None,
                    "height": None,
                }
            )

            for _, file_id in f["ids"].items():
                if file_id in persisted_metadata:
                    m = persisted_metadata[file_id]
                    f["duration"] = m.duration
                    f["width"] = m.width
                    f["height"] = m.height
                    f["updated_at"] = m.updated_at

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
