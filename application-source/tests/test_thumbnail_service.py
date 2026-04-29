"""Tests for the thumbnail generation service."""

from unittest.mock import MagicMock, patch

from app.services.thumbnail_service import extract_video_frame, get_cache_path


def test_get_cache_path():
    """Test generating a standard cache path for a thumbnail."""

    path = get_cache_path("file123")
    assert path.endswith("file123.jpg")
    assert "cache/thumbnails" in path


def test_get_cache_path_with_timestamp():
    """Test generating a cache path for a specific video frame timestamp."""

    path = get_cache_path("file123", timestamp=60)
    assert path.endswith("preview_file123_60.jpg")


@patch("ffmpeg.input")
@patch("ffmpeg.probe")
def test_extract_video_frame_ffmpeg_calls(mock_probe, mock_input):
    """Test that FFmpeg commands are correctly constructed for frame extraction."""

    # Mock probe response
    mock_probe.return_value = {
        "streams": [{"codec_type": "video", "width": 1920, "height": 1080}],
        "format": {"duration": "120.5"},
    }

    # Mock input chain
    mock_chain = MagicMock()
    mock_input.return_value = mock_chain
    mock_chain.filter.return_value = mock_chain
    mock_chain.output.return_value = mock_chain
    mock_chain.overwrite_output.return_value = mock_chain

    stream_url = "http://example.com/video.mp4"
    token = "secret_token"
    cache_path = "/tmp/test.jpg"

    headers = {"Authorization": f"Bearer {token}"}
    duration, width, height = extract_video_frame(stream_url, headers, cache_path)

    # Verify duration and resolution extraction
    assert duration == 120.5
    assert width == 1920
    assert height == 1080

    # Verify FFmpeg input was called with the correct URL and headers
    mock_input.assert_called_once_with(
        stream_url, threads=1, ss="60", headers="Authorization: Bearer secret_token\r\n"
    )

    # Verify filter was applied (AV1 fixes)
    mock_chain.filter.assert_called_once_with(
        "setparams", color_primaries="bt709", color_trc="bt709", colorspace="bt709"
    )

    # Verify output was called with correct parameters
    mock_chain.output.assert_called_once_with(
        cache_path, vframes=1, vcodec="mjpeg", format="image2", **{"qscale:v": 4}
    )
