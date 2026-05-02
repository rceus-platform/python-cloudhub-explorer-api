"""Test script to verify task tracking status across background worker lifecycle."""

import asyncio
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MockThumbnailSyncManager:
    """Mock manager for testing task status tracking."""

    _queue_obj = None
    _active_folders = {}
    _counter = 0
    _queued_ids = set()
    _in_progress = set()

    @classmethod
    def get_queue(cls):
        """Lazy initialization of the priority queue."""
        if cls._queue_obj is None:
            cls._queue_obj = asyncio.PriorityQueue()
        return cls._queue_obj

    @classmethod
    def is_task_active(cls, file_id):
        """Check if a file ID is currently queued or in progress."""
        return file_id in cls._queued_ids or file_id in cls._in_progress

    @classmethod
    async def enqueue(cls, priority, folder_id, file_id, name):
        """Enqueue a mock task with given priority and tracking."""
        cls._counter += 1
        cls._queued_ids.add(file_id)
        await cls.get_queue().put((priority, cls._counter, folder_id, file_id, name))
        logger.info("Enqueued: %s (ID: %s, P:%d)", name, file_id, priority)

    @classmethod
    async def worker(cls):
        """Process tasks from the mock queue and update tracking status."""
        processed = []
        while not cls.get_queue().empty():
            priority, _, folder_id, file_id, name = await cls.get_queue().get()
            cls._queued_ids.discard(file_id)

            active_folder = cls._active_folders.get(1)  # User 1
            if priority > 0 and active_folder != folder_id:
                logger.info("Skipping: %s", name)
                continue

            cls._in_progress.add(file_id)
            logger.info("Processing: %s (Active: %s)", name, cls.is_task_active(file_id))
            processed.append(name)
            await asyncio.sleep(0.01)
            cls._in_progress.remove(file_id)
            logger.info("Finished: %s (Active: %s)", name, cls.is_task_active(file_id))

        return processed


async def test_tracking():
    """Run a scenario to verify task status is tracked correctly."""
    manager = MockThumbnailSyncManager()
    manager._active_folders[1] = "Folder A"

    # 1. Enqueue task
    await manager.enqueue(1, "Folder A", "file_1", "File 1")
    assert manager.is_task_active("file_1") is True

    # 2. Start worker and check mid-process
    # We'll run the worker in a task
    worker_task = asyncio.create_task(manager.worker())
    await asyncio.sleep(0.005)  # Wait for it to start

    # It should be in_progress now
    # Note: in real code, _queued_ids.discard happens before _in_progress.add
    # so there might be a tiny gap, but is_task_active checks both.
    assert manager.is_task_active("file_1") is True

    await worker_task
    assert manager.is_task_active("file_1") is False

    print("\nSUCCESS: Task tracking working as expected!")


if __name__ == "__main__":
    asyncio.run(test_tracking())
