"""Tests for file utilities."""

from app.utils.file_utils import get_media_type


def test_get_media_type_video():
    """Test identifying video media types from filenames."""

    assert get_media_type("movie.mp4") == "video/mp4"


def test_get_media_type_image():
    """Test identifying image media types from filenames."""

    assert get_media_type("photo.jpg") == "image/jpeg"


def test_get_media_type_unknown():
    """Test that unknown extensions fallback to application/octet-stream."""

    # Use something truly random to ensure application/octet-stream fallback
    assert get_media_type("random.unlikelyextension") == "application/octet-stream"
    assert get_media_type("noextension") == "application/octet-stream"
