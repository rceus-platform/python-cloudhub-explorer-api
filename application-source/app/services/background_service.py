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

__all__ = [
    "ThumbnailSyncManager",
    "enqueue_thumbnail",
    "set_active_folder",
    "enqueue_folder_thumbnails",
    "start_worker",
    "sync_thumbnails",
]


class ThumbnailSyncManager:
    """Manager for background thumbnail generation with priority and folder awareness."""

    _queue_obj: asyncio.PriorityQueue[tuple[int, int, int, str, dict]] | None = None
    _in_progress: set[str] = set()
    _active_folders: dict[int, str] = {}
    _worker_tasks: list[asyncio.Task] = []
    _semaphore: asyncio.Semaphore | None = None
    _is_running: bool = False
    _task_counter: int = 0
    _queued_ids: set[str] = set()

    @classmethod
    def get_queue(cls) -> asyncio.PriorityQueue[tuple[int, int, int, str, dict]]:
        """Lazily initialize the priority queue to ensure it's bound to the current event loop."""
        if cls._queue_obj is None:
            cls._queue_obj = asyncio.PriorityQueue()
        return cls._queue_obj

    @classmethod
    def get_semaphore(cls) -> asyncio.Semaphore:
        """Lazily initialize the semaphore to ensure it's bound to the current event loop."""
        if cls._semaphore is None:
            # Optimized for low-resource environments (1GB RAM VM)
            cls._semaphore = asyncio.Semaphore(1)
        return cls._semaphore

    @classmethod
    def is_task_active(cls, file_id: str) -> bool:
        """Check if a file is currently in the queue or being processed."""
        return file_id in cls._queued_ids or file_id in cls._in_progress

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

        if file_id in cls._in_progress or file_id in cls._queued_ids:
            return

        # Check if already exists in cache to avoid redundant queuing
        cache_path = thumbnail_service.get_cache_path(file_id)
        if os.path.exists(cache_path):
            return

        # Priority 0: On-demand (root), Priority 1: Active folder, Priority 2: Background/Inactive
        if folder_id == "root":
            priority = 0
        elif cls._active_folders.get(user_id) == folder_id:
            priority = 1
        else:
            priority = 2

        # Use a counter to avoid comparing file_info dicts and ensure FIFO for same priority
        cls._task_counter += 1
        cls._queued_ids.add(file_id)
        await cls.get_queue().put((priority, cls._task_counter, user_id, folder_id, file_info))
        logger.info(
            "Enqueued thumbnail task for: %s (Priority: %d)", file_info.get("name"), priority
        )

    @classmethod
    async def start_worker(cls) -> None:
        """Initialize and start background worker tasks."""
        if not cls._worker_tasks:
            # Ensure queue is created in the correct loop
            cls.get_queue()

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
            # PriorityQueue returns (priority, counter, user_id, folder_id, file_info)
            priority, _, user_id, folder_id, file_info = await cls.get_queue().get()

            # Extract file_id to manage tracking
            ids = file_info.get("ids", {})
            provider = next(iter(ids.keys())) if ids else None
            file_id = ids[provider] if provider else None

            # 1. Check if folder is still active or task was root
            active_folder = cls._active_folders.get(user_id)
            if priority > 0 and active_folder != folder_id:
                logger.debug("Skipping lower-priority task for inactive folder: %s", folder_id)
                if file_id:
                    cls._queued_ids.discard(file_id)
                cls.get_queue().task_done()
                continue

            # 2. Final existence check before logging "pickup"
            if not file_id:
                cls.get_queue().task_done()
                continue

            cache_path = thumbnail_service.get_cache_path(file_id)
            if os.path.exists(cache_path):
                logger.debug("Skipping redundant task, thumbnail already exists: %s", file_id)
                cls._queued_ids.discard(file_id)
                cls.get_queue().task_done()
                continue

            logger.info(
                "Worker #%d picked up task: %s (Priority: %d)",
                worker_id,
                file_info.get("name"),
                priority,
            )

            try:
                # 3. Check in_progress to avoid concurrent processing (last line of defense)
                if file_id in cls._in_progress:
                    cls._queued_ids.discard(file_id)
                    continue

                cls._in_progress.add(file_id)
                cls._queued_ids.discard(file_id)

                try:
                    semaphore = cls.get_semaphore()
                    if semaphore is not None:
                        async with semaphore:
                            await cls._process_file_thumbnail(
                                user_id, file_info, controller.delay_seconds
                            )
                finally:
                    cls._in_progress.remove(file_id)

                await asyncio.to_thread(controller.update)
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

        logger.info(
            "Generating thumbnail for %s (ID: %s, Provider: %s). Cache path: %s",
            file_name,
            file_id,
            provider,
            os.path.abspath(cache_path),
        )

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
                    mega_password = account.refresh_token or account.sid_or_token
                    if not mega_password:
                        logger.warning(
                            "Skipping MEGA thumbnail for %s: missing credentials", account.email
                        )
                        return
                    stream_url = f"http://localhost:4000/stream?fileId={real_file_id}"
                    headers["X-Mega-Email"] = str(account.email or account.access_token)
                    headers["X-Mega-Password"] = str(mega_password)
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
        """Recursively identify all media files and enqueue them for thumbnail generation."""
        if cls._is_running:
            logger.info("Sync already in progress for user %d", user_id)
            return

        cls._is_running = True
        logger.info("Starting global thumbnail sync for user %d", user_id)

        try:
            with SessionLocal() as db:
                accounts = account_service.get_user_accounts(db, user_id)

                for account in accounts:
                    logger.info(
                        "Syncing thumbnails for account: %s (%s)", account.email, account.provider
                    )
                    media_files = []

                    if account.provider == "gdrive":
                        # Import here to avoid circular dependencies
                        from app.services.gdrive_service import list_all_media as gdrive_sync

                        media_files = await asyncio.to_thread(gdrive_sync, account, db)

                    elif account.provider == "mega":
                        from app.services.mega_service import get_mega_session

                        m = await asyncio.to_thread(
                            get_mega_session, account.access_token, account.refresh_token
                        )
                        if m:
                            # Pass None as folder_id to signal 'all files' if supported,
                            # or just fetch all and filter manually
                            all_nodes = await asyncio.to_thread(m.get_files)
                            if all_nodes:
                                for node_id, node_data in all_nodes.items():
                                    # Type 0 is file, Type 1 is folder
                                    if node_data.get("t") == 0:
                                        name = node_data.get("a", {}).get("n", "unknown")
                                        if any(
                                            name.lower().endswith(ext)
                                            for ext in [
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
                                            ]
                                        ):
                                            media_files.append(
                                                {
                                                    "ids": {"mega": f"{account.email}:{node_id}"},
                                                    "name": name,
                                                    "type": "file",
                                                }
                                            )

                    logger.info("Found %d media files for %s", len(media_files), account.email)
                    for f in media_files:
                        # Use priority 2 for background sync tasks
                        await cls.enqueue_thumbnail(user_id, "background", f)

        except Exception:
            logger.exception("Error during global thumbnail sync")
        finally:
            cls._is_running = False
            logger.info("Global thumbnail sync finished for user %d", user_id)


# Export for convenience
enqueue_thumbnail = ThumbnailSyncManager.enqueue_thumbnail
set_active_folder = ThumbnailSyncManager.set_active_folder
enqueue_folder_thumbnails = ThumbnailSyncManager.enqueue_folder_thumbnails
start_worker = ThumbnailSyncManager.start_worker
sync_thumbnails = ThumbnailSyncManager.sync_thumbnails
