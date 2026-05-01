import unittest
from unittest.mock import MagicMock, patch

from app.utils.resource_manager import AdaptiveController


class TestAdaptiveController(unittest.TestCase):
    def setUp(self):
        self.controller = AdaptiveController()

    @patch("psutil.cpu_percent")
    @patch("psutil.virtual_memory")
    def test_update_high_load(self, mock_mem, mock_cpu):
        # Set high load
        mock_cpu.return_value = 90.0
        mock_mem.return_value.percent = 30.0

        initial_workers = self.controller.max_workers
        initial_batch = self.controller.batch_size
        initial_delay = self.controller.delay_seconds

        self.controller.update()

        self.assertLess(self.controller.max_workers, initial_workers + 1)
        self.assertLess(self.controller.batch_size, initial_batch + 1)
        self.assertGreater(self.controller.delay_seconds, initial_delay)

    @patch("psutil.cpu_percent")
    @patch("psutil.virtual_memory")
    def test_update_low_load(self, mock_mem, mock_cpu):
        # Set low load
        mock_cpu.return_value = 10.0
        mock_mem.return_value.percent = 10.0

        initial_workers = self.controller.max_workers
        initial_batch = self.controller.batch_size
        initial_delay = self.controller.delay_seconds

        self.controller.update()

        # Should scale up or stay at max
        self.assertTrue(self.controller.max_workers >= initial_workers)
        self.assertTrue(self.controller.batch_size >= initial_batch)
        self.assertLess(self.controller.delay_seconds, initial_delay + 0.1)


if __name__ == "__main__":
    unittest.main()
