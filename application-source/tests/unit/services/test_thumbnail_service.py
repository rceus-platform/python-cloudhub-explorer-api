"""Tests for the thumbnail generation service."""

from unittest.mock import MagicMock, patch

import pytest

from app.services.thumbnail_service import (
    extract_video_frame,
    get_cache_path,
    process_image_thumbnail,
    save_metadata,
)


def test_get_cache_path():
    """Test generating a standard cache path for a thumbnail."""

    path = get_cache_path("file123")
    assert path.endswith("file123.jpg")
    assert "thumbnails" in path


def test_get_cache_path_with_timestamp():
    """Test generating a cache path for a specific video frame timestamp."""

    path = get_cache_path("file123", timestamp=60)
    assert path.endswith("preview_file123_60.jpg")


@patch("subprocess.run")
@patch("ffmpeg.input")
@patch("ffmpeg.probe")
def test_extract_video_frame_ffmpeg_calls(mock_probe, mock_input, mock_run):
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
    mock_chain.compile.return_value = ["ffmpeg", "-i", "some_url"]

    stream_url = "http://example.com/video.mp4"
    token = "secret_token"
    cache_path = "/tmp/test.jpg"

    headers = {"Authorization": f"Bearer {token}"}
    duration, width, height = extract_video_frame(stream_url, headers, cache_path)

    # Verify duration and resolution extraction
    assert duration == 120.5
    assert width == 1920
    assert height == 1080

    # Verify FFmpeg input was called
    mock_input.assert_called()

    # Verify subprocess.run was called
    mock_run.assert_called_once_with(
        ["ffmpeg", "-i", "some_url"], capture_output=True, timeout=30, check=True
    )


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
@patch("PIL.Image.open")
async def test_process_image_thumbnail(mock_image_open, mock_get):
    """Test processing an image for thumbnail generation."""

    # Mock HTTP response
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"fake_image_data"
    mock_get.return_value = mock_resp

    # Mock PIL Image
    mock_img = MagicMock()
    mock_img.size = (1000, 500)
    mock_img.resize.return_value = mock_img
    mock_img.convert.return_value = mock_img
    mock_image_open.return_value = mock_img

    stream_url = "http://example.com/image.jpg"
    headers = {"Authorization": "Bearer token"}
    cache_path = "/tmp/thumb.jpg"

    with patch("PIL.ImageOps.exif_transpose", return_value=mock_img):
        size = await process_image_thumbnail(stream_url, headers, cache_path)

    assert size == (1000, 500)
    mock_get.assert_called_once_with(stream_url, headers=headers)
    mock_img.resize.assert_called_once()
    mock_img.convert.assert_called_once_with("RGB")
    mock_img.save.assert_called_once()


def test_save_metadata(mock_db):
    """Test saving file metadata to the database."""

    # Mock no existing metadata
    mock_db.query.return_value.filter.return_value.first.return_value = None

    file_id = "file123"
    save_metadata(mock_db, file_id, "gdrive", "movie.mp4", 120.5, 1920, 1080)

    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()

    # Verify object attributes
    added_obj = mock_db.add.call_args[0][0]
    assert added_obj.file_id == file_id
    assert added_obj.provider == "gdrive"
    assert added_obj.name == "movie.mp4"
    assert added_obj.duration == "120"
    assert added_obj.width == 1920
    assert added_obj.height == 1080


def test_get_cache_path_settings():
    """Test get_cache_path with THUMBNAIL_DIR setting."""
    with patch("app.services.thumbnail_service.settings") as mock_settings:
        with patch("os.path.exists", return_value=True):
            with patch("os.makedirs"):
                mock_settings.THUMBNAIL_DIR = "/custom/dir"
                path = get_cache_path("f1")
                assert path.startswith("/custom/dir")


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_process_image_thumbnail_failure(mock_get):
    """Test process_image_thumbnail with HTTP failure."""
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.text = "Not Found"
    mock_get.return_value = mock_resp
    import httpx

    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "404", request=MagicMock(), response=mock_resp
    )

    with pytest.raises(httpx.HTTPStatusError):
        await process_image_thumbnail("http://url", {}, "/tmp/p.jpg")


@patch("subprocess.run")
@patch("ffmpeg.input")
@patch("ffmpeg.probe")
def test_extract_video_frame_probe_fail(mock_probe, mock_input, mock_run):
    """Test extract_video_frame when ffprobe fails."""
    mock_probe.side_effect = Exception("Probe failed")
    mock_chain = MagicMock()
    mock_input.return_value = mock_chain
    mock_chain.filter.return_value = mock_chain
    mock_chain.output.return_value = mock_chain
    mock_chain.compile.return_value = ["ffmpeg"]

    # Should continue to extraction even if probe fails
    extract_video_frame("http://url", {}, "/tmp/p.jpg")
    mock_run.assert_called_once()


@patch("subprocess.run")
@patch("ffmpeg.input")
@patch("ffmpeg.probe")
def test_extract_video_frame_timeout(mock_probe, _mock_input, mock_run):
    """Test extract_video_frame handling FFmpeg timeout."""
    mock_probe.return_value = {"streams": [], "format": {"duration": "10"}}
    import subprocess

    mock_run.side_effect = subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=30)

    with pytest.raises(RuntimeError) as exc:
        extract_video_frame("http://url", {}, "/tmp/p.jpg")
    assert "timeout" in str(exc.value).lower()


@patch("subprocess.run")
@patch("ffmpeg.input")
@patch("ffmpeg.probe")
def test_extract_video_frame_process_error(mock_probe, _mock_input, mock_run):
    """Test extract_video_frame handling FFmpeg process error."""
    mock_probe.return_value = {"streams": [], "format": {"duration": "10"}}
    import subprocess

    mock_run.side_effect = subprocess.CalledProcessError(
        returncode=1, cmd=["ffmpeg"], stderr=b"Generic Error"
    )

    with pytest.raises(RuntimeError) as exc:
        extract_video_frame("http://url", {}, "/tmp/p.jpg")
    assert "Generic Error" in str(exc.value)


@patch("subprocess.run")
@patch("ffmpeg.input")
@patch("ffmpeg.probe")
def test_extract_video_frame_unexpected_error(mock_probe, _mock_input, mock_run):
    """Test extract_video_frame handling unexpected exceptions."""
    mock_probe.return_value = {"streams": [], "format": {"duration": "10"}}
    mock_run.side_effect = ValueError("Unexpected")

    with pytest.raises(ValueError):
        extract_video_frame("http://url", {}, "/tmp/p.jpg")
