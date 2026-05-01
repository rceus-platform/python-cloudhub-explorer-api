"""Resource Manager Module.

Provides adaptive control of background task parameters based on system resource usage.
"""

import logging
import multiprocessing

import psutil

logger = logging.getLogger(__name__)


class AdaptiveController:
    """Dynamically adjusts concurrency and workload based on CPU and RAM usage."""

    def __init__(self):
        self.cpu_count = multiprocessing.cpu_count()

        # Initial values
        self.max_workers = max(1, self.cpu_count // 2)
        self.batch_size = 20
        self.delay_seconds = 2.0

        # Limits
        self.min_workers = 1
        self.max_workers_limit = self.cpu_count

        self.min_batch = 1
        self.max_batch = 50

        self.min_delay = 0.5
        self.max_delay = 15.0

    def get_metrics(self) -> tuple[float, float]:
        """Fetch current CPU and RAM usage percentages."""
        # interval=0.5 blocks for 0.5s, providing a more accurate measurement
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory().percent
        return cpu, mem

    def update(self) -> None:
        """Adjust parameters based on current system load."""
        cpu, mem = self.get_metrics()

        # High load (CPU > 80% or RAM > 90%) → scale down fast
        if cpu > 80 or mem > 90:
            self.max_workers = max(self.min_workers, self.max_workers - 2)
            self.batch_size = max(self.min_batch, self.batch_size - 5)
            self.delay_seconds = min(self.max_delay, self.delay_seconds + 3.0)

        # Medium load (CPU > 60% or RAM > 85%) → slight tuning
        elif cpu > 60 or mem > 85:
            self.max_workers = max(self.min_workers, self.max_workers - 1)
            self.batch_size = max(self.min_batch, self.batch_size - 2)
            self.delay_seconds = min(self.max_delay, self.delay_seconds + 1.0)

        # Low load (CPU < 60% and RAM < 85%) → scale up aggressively
        else:
            self.max_workers = min(self.max_workers_limit, self.max_workers + 2)
            self.batch_size = min(self.max_batch, self.batch_size + 5)
            self.delay_seconds = max(self.min_delay, self.delay_seconds - 1.5)

        logger.info(
            "[Adaptive] CPU: %.1f%% | MEM: %.1f%% | workers=%d | batch=%d | delay=%.1fs",
            cpu,
            mem,
            self.max_workers,
            self.batch_size,
            self.delay_seconds,
        )
