"""Background Service Module.

Responsibilities:
- Manage background tasks like thumbnail synchronization
- Provide rate-limited traversal of files across linked accounts
"""

import asyncio
import json
import logging
import os

from app.core.config import settings
from app.db import models
from app.db.session import SessionLocal
from app.services import account_service, library_service, thumbnail_service
from app.services.gdrive_service import get_valid_access_token
from app.utils.file_utils import get_media_type

logger = logging.getLogger(__name__)


class ThumbnailSyncManager:
    """Manager for background thumbnail synchronization tasks."""

    _is_running = False

    @classmethod
    async def sync_thumbnails(cls, user_id: int) -> None:
        """Background worker that iterates through all files and generates thumbnails."""

        if cls._is_running:
            logger.info("Thumbnail sync already running, skipping.")
            return

        cls._is_running = True
        try:
            logger.info("Starting thumbnail sync for user %d", user_id)

            # Fetch accounts using a short-lived session
            with SessionLocal() as db:
                accounts = account_service.get_user_accounts(db, user_id)

            if not accounts:
                logger.info("No accounts found for user.")
                return

            # Keep track of folders to visit: (folder_id, folder_name)
            folders_to_visit = [("root", "root")]

            while folders_to_visit:
                current_folder_id, current_folder_name = folders_to_visit.pop(0)
                logger.info("Syncing folder: %s (%s)", current_folder_name, current_folder_id)

                # We need to resolve the correct accounts for the current folder
                target_accounts = accounts
                if current_folder_id != "root":
                    try:
                        folder_map = json.loads(current_folder_id)
                        target_accounts = [acc for acc in accounts if acc.provider in folder_map]
                    except (json.JSONDecodeError, TypeError):
                        pass

                # Fetch files in the current folder using a short-lived session
                try:
                    with SessionLocal() as db:
                        files = await library_service.list_all_files(
                            db, target_accounts, current_folder_id
                        )
                except Exception:
                    logger.exception("Error fetching files for folder %s", current_folder_id)
                    continue

                for file_info in files:
                    if file_info["type"] == "folder":
                        subfolder_id = (
                            json.dumps(file_info["ids"])
                            if "ids" in file_info
                            else file_info.get("id")
                        )
                        folders_to_visit.append((subfolder_id, file_info["name"]))
                    elif file_info["type"] == "file":
                        await cls._process_file_thumbnail(user_id, file_info)

        except Exception:
            logger.exception("Thumbnail sync failed")
        finally:
            cls._is_running = False
            logger.info("Thumbnail sync completed.")

    @classmethod
    async def _process_file_thumbnail(cls, user_id: int, file_info: dict) -> None:
        """Check if a file needs a thumbnail and generate it if necessary."""

        file_name = file_info.get("name", "")
        media_type = get_media_type(file_name)

        # We only care about images and videos
        if not (media_type.startswith("image/") or media_type.startswith("video/")):
            return

        # file_info contains 'ids' map: { "provider": "email:id" }
        ids = file_info.get("ids", {})
        if not ids:
            return

        provider = next(iter(ids.keys()))
        file_id = ids[provider]

        # Check if we already have a thumbnail for this exact file_id
        cache_path = thumbnail_service.get_cache_path(file_id)
        if os.path.exists(cache_path):
            return

        # Check DB metadata
        with SessionLocal() as db:
            metadata = (
                db.query(models.FileMetadata).filter(models.FileMetadata.file_id == file_id).first()
            )
            if metadata and metadata.thumbnail_path and os.path.exists(cache_path):
                return

        logger.info("Generating thumbnail for %s (%s) via %s", file_name, file_id, provider)

        try:
            # Resolve account
            with SessionLocal() as db:
                if ":" in file_id:
                    email, real_file_id = file_id.split(":", 1)
                    account = account_service.get_account_by_email(db, user_id, provider, email)
                else:
                    account = account_service.get_provider_account(db, user_id, provider)
                    real_file_id = file_id

                if not account:
                    logger.warning("Could not resolve account for %s", file_id)
                    return

                # Prepare stream URL and headers
                headers = {}
                token = get_valid_access_token(account, db) if provider == "gdrive" else None

                if provider == "gdrive":
                    stream_url = (
                        f"https://www.googleapis.com/drive/v3/files/{real_file_id}?alt=media"
                    )
                    if token:
                        headers["Authorization"] = f"Bearer {token}"
                elif provider == "mega":
                    stream_url = f"http://localhost:4000/stream?fileId={real_file_id}"
                    headers["X-Mega-Email"] = str(account.access_token)
                    headers["X-Mega-Password"] = str(account.refresh_token)
                    if settings.INTERNAL_SECRET:
                        headers["X-Internal-Secret"] = settings.INTERNAL_SECRET
                else:
                    return

            is_image = media_type.startswith("image/")

            # Run in thread pool to avoid blocking the async event loop
            if is_image:
                await asyncio.to_thread(
                    thumbnail_service.process_image_thumbnail,
                    stream_url,
                    headers,
                    cache_path,
                )
                duration, width, height = 0, None, None
            else:
                duration, width, height = await asyncio.to_thread(
                    thumbnail_service.extract_video_frame,
                    stream_url,
                    headers,
                    cache_path,
                    None,
                )

            with SessionLocal() as db:
                thumbnail_service.save_metadata(
                    db, file_id, provider, file_name, duration, width, height
                )

            # Invalidate in-memory cache
            from app.services import file_cache

            file_cache.invalidate_all(user_id)

            logger.info("Successfully generated thumbnail for %s", file_name)

            # Rate limit: 10 seconds delay between files to prevent OOM / MEGA blocks
            await asyncio.sleep(10)

        except Exception:
            logger.exception("Failed to generate thumbnail for %s", file_name)
            # Add a delay even on failure to avoid rapid error loops
            await asyncio.sleep(10)


# Export the sync function for convenience
sync_thumbnails = ThumbnailSyncManager.sync_thumbnails
