"""Tests for the adaptive resource controller."""

from unittest.mock import patch

from app.utils.resource_manager import AdaptiveController


def test_adaptive_controller_high_load():
    """Test controller behavior under high CPU/Memory load."""

    controller = AdaptiveController()
    controller.max_workers = 10
    controller.batch_size = 20
    controller.delay_seconds = 2.0

    with patch.object(AdaptiveController, "get_metrics", return_value=(90, 95)):
        controller.update()
        assert controller.max_workers == 8
        assert controller.batch_size == 15
        assert controller.delay_seconds == 5.0


def test_adaptive_controller_medium_load():
    """Test controller behavior under moderate load."""

    controller = AdaptiveController()
    controller.max_workers = 10
    controller.batch_size = 20
    controller.delay_seconds = 2.0

    with patch.object(AdaptiveController, "get_metrics", return_value=(70, 80)):
        controller.update()
        assert controller.max_workers == 9
        assert controller.batch_size == 18
        assert controller.delay_seconds == 3.0


def test_adaptive_controller_low_load():
    """Test controller behavior under low load (increasing resources)."""

    controller = AdaptiveController()
    controller.max_workers = 4
    controller.batch_size = 10
    controller.delay_seconds = 5.0

    with patch.object(AdaptiveController, "get_metrics", return_value=(10, 10)):
        controller.update()
        assert controller.max_workers == 6
        assert controller.batch_size == 15
        assert controller.delay_seconds == 3.5
