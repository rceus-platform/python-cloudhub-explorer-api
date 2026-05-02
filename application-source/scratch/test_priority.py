"""Test script to verify background service priority and skipping logic."""

import asyncio
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MockThumbnailSyncManager:
    """Mock manager for testing background task prioritization."""

    _queue_obj = None
    _active_folders = {}
    _counter = 0

    @classmethod
    def get_queue(cls):
        """Lazy initialization of the priority queue."""
        if cls._queue_obj is None:
            cls._queue_obj = asyncio.PriorityQueue()
        return cls._queue_obj

    @classmethod
    async def enqueue(cls, priority, folder_id, name):
        """Enqueue a mock task with given priority."""
        cls._counter += 1
        await cls.get_queue().put((priority, cls._counter, folder_id, name))
        logger.info("Enqueued: %s (P:%d, C:%d, F:%s)", name, priority, cls._counter, folder_id)

    @classmethod
    async def worker(cls):
        """Process tasks from the mock queue and return results."""
        processed = []
        skipped = []
        while not cls.get_queue().empty():
            priority, _, folder_id, name = await cls.get_queue().get()
            active_folder = cls._active_folders.get(1)  # User 1

            if priority > 0 and active_folder != folder_id:
                logger.info("Skipping: %s (Folder %s inactive)", name, folder_id)
                skipped.append(name)
                continue

            logger.info("Processing: %s", name)
            processed.append(name)
            # Simulate work
            await asyncio.sleep(0.01)
        return processed, skipped


async def test_prioritization():
    """Run a scenario to verify tasks are prioritized and skipped correctly."""
    manager = MockThumbnailSyncManager()
    manager._active_folders[1] = "Folder A"

    # 1. Enqueue background tasks (Priority 2)
    for i in range(5):
        await manager.enqueue(2, "background", f"BG_{i}")

    # 2. Enqueue Folder A tasks (Priority 1)
    for i in range(3):
        await manager.enqueue(1, "Folder A", f"A_{i}")

    # 3. Change active folder to B
    manager._active_folders[1] = "Folder B"

    # 4. Enqueue Folder B tasks (Priority 1)
    for i in range(2):
        await manager.enqueue(1, "Folder B", f"B_{i}")

    # 5. Add a priority 0 task (Root)
    await manager.enqueue(0, "root", "ROOT_1")

    logger.info("--- Starting Worker ---")
    processed, skipped = await manager.worker()

    logger.info("Processed: %s", processed)
    logger.info("Skipped: %s", skipped)

    # Expectations:
    # 1. ROOT_1 (P0) processed first
    # 2. B_0, B_1 (P1, active) processed next
    # 3. A_0, A_1, A_2 (P1, inactive) skipped
    # 4. BG_0...BG_4 (P2, inactive) skipped

    assert processed[0] == "ROOT_1"
    assert "B_0" in processed
    assert "B_1" in processed
    assert "A_0" in skipped
    assert "BG_0" in skipped

    print("\nSUCCESS: Prioritization and skipping working as expected!")


if __name__ == "__main__":
    asyncio.run(test_prioritization())
