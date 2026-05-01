"""Background Service Module.

Responsibilities:
- Manage background tasks like thumbnail synchronization
- Provide rate-limited traversal of files across linked accounts
"""

import asyncio
import logging
import os

from app.core.config import settings
from app.db.session import SessionLocal
from app.services import account_service, thumbnail_service
from app.services.gdrive_service import get_valid_access_token
from app.utils.file_utils import get_media_type
from app.utils.resource_manager import AdaptiveController

logger = logging.getLogger(__name__)


class ThumbnailManager:
    """Manager for background thumbnail generation with priority and folder awareness."""

    _queue_obj: asyncio.Queue[tuple[int, str, dict]] | None = None
    _in_progress: set[str] = set()
    _active_folders: dict[int, str] = {}
    _worker_tasks: list[asyncio.Task] = []
    _semaphore: asyncio.Semaphore | None = None

    @classmethod
    def get_queue(cls) -> asyncio.Queue[tuple[int, str, dict]]:
        """Lazily initialize the queue to ensure it's bound to the current event loop."""
        if cls._queue_obj is None:
            cls._queue_obj = asyncio.Queue()
        return cls._queue_obj

    @classmethod
    def get_semaphore(cls) -> asyncio.Semaphore:
        """Lazily initialize the semaphore to ensure it's bound to the current event loop."""
        if cls._semaphore is None:
            # Optimized for low-resource environments (1GB RAM VM)
            cls._semaphore = asyncio.Semaphore(1)
        return cls._semaphore

    @classmethod
    def set_active_folder(cls, user_id: int, folder_id: str) -> None:
        """Mark a folder as active for a user to prioritize its thumbnails."""
        cls._active_folders[user_id] = folder_id
        logger.info("User %d active folder set to %s", user_id, folder_id)

    @classmethod
    async def enqueue_folder_thumbnails(
        cls, user_id: int, folder_id: str, files: list[dict]
    ) -> None:
        """Enqueue all media files in a folder that are missing thumbnails."""
        for f in files:
            # We don't check for updated_at here anymore;
            # enqueue_thumbnail will handle the check against the actual disk cache.
            if f.get("type") == "file":
                await cls.enqueue_thumbnail(user_id, folder_id, f)

    @classmethod
    async def enqueue_thumbnail(cls, user_id: int, folder_id: str, file_info: dict) -> None:
        """Add a single file to the generation queue if not already present."""
        ids = file_info.get("ids", {})
        if not ids:
            return

        provider = next(iter(ids.keys()))
        file_id = ids[provider]

        if file_id in cls._in_progress:
            return

        # Check if already exists in cache to avoid redundant queuing
        cache_path = thumbnail_service.get_cache_path(file_id)
        if os.path.exists(cache_path):
            return

        await cls.get_queue().put((user_id, folder_id, file_info))
        logger.info("Enqueued thumbnail task for: %s", file_info.get("name"))

    @classmethod
    async def start_worker(cls) -> None:
        """Start background worker tasks."""
        if not cls._worker_tasks:
            # Launch only 1 worker to save RAM on 1GB VMs
            for i in range(1):
                task = asyncio.create_task(cls._worker_loop(i))
                cls._worker_tasks.append(task)
            logger.info("Started 1 thumbnail background worker (Low Resource Mode).")

    @classmethod
    async def _worker_loop(cls, worker_id: int) -> None:
        """Main loop for processing the thumbnail queue (Worker #worker_id)."""
        logger.info("Thumbnail worker #%d starting...", worker_id)
        controller = AdaptiveController()

        while True:
            user_id, folder_id, file_info = await cls.get_queue().get()
            try:
                # 1. Check if folder is still active
                active_folder = cls._active_folders.get(user_id)
                if active_folder != folder_id:
                    logger.info(
                        "Skipping task for inactive folder: %s (current active: %s)",
                        folder_id,
                        active_folder,
                    )
                    continue

                # 2. Get file_id and check in_progress
                ids = file_info.get("ids", {})
                if not ids:
                    continue
                provider = next(iter(ids.keys()))
                file_id = ids[provider]

                if file_id in cls._in_progress:
                    continue

                cls._in_progress.add(file_id)
                try:
                    semaphore = cls.get_semaphore()
                    # Explicit check to satisfy static analysis
                    if semaphore is not None:
                        async with semaphore:
                            await cls._process_file_thumbnail(
                                user_id, file_info, controller.delay_seconds
                            )
                finally:
                    cls._in_progress.remove(file_id)

                controller.update()
            except Exception:
                logger.exception("Error in thumbnail worker loop")
            finally:
                cls.get_queue().task_done()

    @classmethod
    async def _process_file_thumbnail(
        cls, user_id: int, file_info: dict, delay_seconds: float = 2.0
    ) -> None:
        """Core logic to generate a single thumbnail (moved from original manager)."""

        file_name = file_info.get("name", "")
        media_type = get_media_type(file_name)

        if not (media_type.startswith("image/") or media_type.startswith("video/")):
            return

        ids = file_info.get("ids", {})
        provider = next(iter(ids.keys()))
        file_id = ids[provider]
        cache_path = thumbnail_service.get_cache_path(file_id)

        # Final existence check before heavy lifting
        if os.path.exists(cache_path):
            return

        logger.info("Generating thumbnail for %s (%s)", file_name, file_id)

        try:
            with SessionLocal() as db:
                if ":" in file_id:
                    email, real_file_id = file_id.split(":", 1)
                    account = account_service.get_account_by_email(db, user_id, provider, email)
                else:
                    account = account_service.get_provider_account(db, user_id, provider)
                    real_file_id = file_id

                if not account:
                    return

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
            if is_image:
                await thumbnail_service.process_image_thumbnail(stream_url, headers, cache_path)
                duration, width, height = 0, None, None
            else:
                duration, width, height = await asyncio.to_thread(
                    thumbnail_service.extract_video_frame, stream_url, headers, cache_path, None
                )

            with SessionLocal() as db:
                thumbnail_service.save_metadata(
                    db, file_id, provider, file_name, duration, width, height
                )

            # Invalidate in-memory cache to notify UI on next poll
            from app.services import file_cache

            file_cache.invalidate_all(user_id)

            logger.info("Successfully generated thumbnail for %s", file_name)
            await asyncio.sleep(delay_seconds)

        except Exception:
            logger.exception("Failed to generate thumbnail for %s", file_name)
            # Mark as attempted (even if failed) to stop the frontend polling loop
            try:
                with SessionLocal() as db:
                    thumbnail_service.save_metadata(
                        db, file_id, provider, file_name, None, None, None
                    )
            except Exception:
                logger.error("Failed to save failure metadata for %s", file_name)
            await asyncio.sleep(delay_seconds)

    @classmethod
    async def sync_thumbnails(cls, user_id: int) -> None:
        """Legacy support for full sync, now just enqueues everything."""
        logger.info("Triggering full sync for user %d (legacy support)", user_id)


# Export for convenience
enqueue_thumbnail = ThumbnailManager.enqueue_thumbnail
set_active_folder = ThumbnailManager.set_active_folder
enqueue_folder_thumbnails = ThumbnailManager.enqueue_folder_thumbnails
start_worker = ThumbnailManager.start_worker
