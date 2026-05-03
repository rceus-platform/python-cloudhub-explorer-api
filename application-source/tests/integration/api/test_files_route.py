"""Integration tests for the files route."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db import models
from app.services import file_cache


async def _aiter_bytes(chunks):
    for chunk in chunks:
        yield chunk


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the in-memory file cache before each test."""
    file_cache._CACHE.clear()
    yield
    file_cache._CACHE.clear()


def test_list_files_empty(client, mock_db):
    """Test listing files when the library is empty."""

    acc = models.Account(
        id=1, user_id=1, email="test@gdrive.com", provider="gdrive", access_token="t1"
    )
    mock_db._query_results[models.Account] = [acc]

    with patch("app.services.library_service.list_all_files", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = []
        response = client.get("/files/")
        assert response.status_code == 200
        assert response.json()["files"] == []


def test_list_files_with_results(client, mock_db):
    """Test listing files when results are present."""

    acc = models.Account(
        id=1, user_id=1, email="test@gdrive.com", provider="gdrive", access_token="t1"
    )
    mock_db._query_results[models.Account] = [acc]

    file_data = {
        "name": "video.mp4",
        "type": "file",
        "ids": {"gdrive": "fid1"},
        "providers": ["gdrive"],
    }
    with patch("app.services.library_service.list_all_files", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = [file_data]
        with patch("app.services.library_service.inject_metadata") as mock_inject:
            mock_inject.return_value = [file_data]

            response = client.get("/files/")
            assert response.status_code == 200
            assert len(response.json()["files"]) == 1


def test_stream_file_unauthorized(client, mock_db):
    """Test streaming a file when credentials are not found."""

    # No credentials found
    mock_db._query_results[models.Account] = []

    response = client.get("/files/stream?provider=gdrive&file_id=fid1")
    assert response.status_code == 404
    assert response.json()["detail"] == "Credentials not found"


def test_list_files_cache_hit_memory(client):
    """Test listing files with an in-memory cache hit."""

    # Set up cache
    cached_data = {"folder_id": "root", "files": [{"name": "cached.mp4"}]}
    file_cache.set_data(1, "root", cached_data)

    response = client.get("/files/")
    assert response.status_code == 200
    assert response.json() == cached_data


def test_list_files_cache_hit_db(client, mock_db):
    """Test listing files with a database cache hit."""

    acc = models.Account(
        id=1, user_id=1, email="test@gdrive.com", provider="gdrive", access_token="t1"
    )
    mock_db._query_results[models.Account] = [acc]

    cached_files = [{"name": "db_cached.mp4", "provider": "gdrive"}]
    with patch("app.services.library_service.get_cached_folder", return_value=cached_files):
        with patch("app.services.library_service.inject_metadata", return_value=cached_files):
            response = client.get("/files/")
            assert response.status_code == 200
            assert response.json()["files"][0]["name"] == "db_cached.mp4"


def test_list_files_complex_folder_id(client, mock_db):
    """Test listing files with a complex JSON folder_id."""

    acc = models.Account(
        id=1, user_id=1, email="test@gdrive.com", provider="gdrive", access_token="t1"
    )
    mock_db._query_results[models.Account] = [acc]

    folder_id = '{"gdrive": "fid1"}'
    with patch("app.services.library_service.get_cached_folder", return_value=None):
        with patch(
            "app.services.library_service.list_all_files", new_callable=AsyncMock
        ) as mock_list:
            mock_list.return_value = []
            response = client.get(f"/files/?folder_id={folder_id}")
            assert response.status_code == 200
            # Check that normalization occurred (sorted keys)
            mock_list.assert_called_once()


def test_list_files_refresh(client, mock_db):
    """Test listing files with refresh=True to bypass cache."""

    acc = models.Account(
        id=1, user_id=1, email="test@gdrive.com", provider="gdrive", access_token="t1"
    )
    mock_db._query_results[models.Account] = [acc]

    with patch("app.services.library_service.list_all_files", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = []
        response = client.get("/files/?refresh=true")
        assert response.status_code == 200
        mock_list.assert_called_once()


def test_stream_file_gdrive(client, mock_db):
    """Test streaming a file from GDrive."""

    acc = models.Account(
        id=1, user_id=1, email="test@gdrive.com", provider="gdrive", access_token="t1"
    )
    mock_db._query_results[models.Account] = [acc]

    with patch("app.api.routes.files.get_valid_access_token", return_value="token"):
        # Mock httpx AsyncClient.stream and AsyncClient.get
        with patch("httpx.AsyncClient.stream") as mock_stream:
            mock_stream.return_value.__aenter__.return_value.status_code = 200
            mock_stream.return_value.__aenter__.return_value.headers = {"Content-Length": "100"}
            mock_stream.return_value.__aenter__.return_value.aiter_bytes.return_value = _aiter_bytes([
                b"data"
            ])

            response = client.get("/files/stream?provider=gdrive&file_id=test@gdrive.com:fid1")
            assert response.status_code == 200


def test_get_thumbnail_custom_timestamp(client, mock_db):
    """Test extracting a thumbnail for a custom timestamp."""

    acc = models.Account(
        id=1, user_id=1, email="test@gdrive.com", provider="gdrive", access_token="t1"
    )
    mock_db._query_results[models.Account] = [acc]

    with patch("app.api.routes.files.get_valid_access_token", return_value="token"):
        with patch(
            "app.services.thumbnail_service.extract_video_frame", return_value=(120, 1280, 720)
        ):
            with patch("app.api.routes.files.FileResponse") as mock_file_response:
                mock_file_response.return_value.status_code = 200
                response = client.get("/files/thumbnail?provider=gdrive&file_id=fid1&timestamp=60")
                assert response.status_code == 200


def test_update_thumbnail_upload(client, mock_db):
    """Test updating a thumbnail via file upload."""

    acc = models.Account(
        id=1, user_id=1, email="test@gdrive.com", provider="gdrive", access_token="t1"
    )
    mock_db._query_results[models.Account] = [acc]

    mock_meta = models.FileMetadata(file_id="fid1", updated_at=123)
    mock_db._query_results[models.FileMetadata] = [mock_meta]

    file_content = b"fake image content"
    files = {"file": ("test.jpg", file_content, "image/jpeg")}

    with patch("PIL.Image.open"):
        with patch("app.services.thumbnail_service.save_metadata"):
            response = client.patch("/files/fid1/thumbnail?provider=gdrive", files=files)
            assert response.status_code == 200
            assert response.json()["success"] is True


def test_update_thumbnail_timestamp(client, mock_db):
    """Test updating a thumbnail via timestamp capture."""

    acc = models.Account(
        id=1, user_id=1, email="test@gdrive.com", provider="gdrive", access_token="t1"
    )
    mock_db._query_results[models.Account] = [acc]

    mock_meta = models.FileMetadata(file_id="fid1", updated_at=123)
    mock_db._query_results[models.FileMetadata] = [mock_meta]

    with patch("app.api.routes.files.get_valid_access_token", return_value="token"):
        with patch(
            "app.services.thumbnail_service.extract_video_frame", return_value=(120, 1280, 720)
        ):
            with patch("app.services.thumbnail_service.save_metadata"):
                response = client.patch("/files/fid1/thumbnail?provider=gdrive&timestamp=60")
                assert response.status_code == 200
                assert response.json()["success"] is True


def test_stream_file_unsupported_provider(client, mock_db):
    """Test streaming from an unsupported provider."""

    acc = models.Account(
        id=1, user_id=1, email="test@other.com", provider="other", access_token="t1"
    )
    mock_db._query_results[models.Account] = [acc]

    response = client.get("/files/stream?provider=other&file_id=fid1")
    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported provider"


def test_get_thumbnail_disk_hit(client):
    """Test getting a thumbnail with a disk cache hit."""

    with patch("os.path.exists", return_value=True):
        with patch("app.api.routes.files.FileResponse") as mock_file_response:
            mock_file_response.return_value.status_code = 200
            response = client.get("/files/thumbnail?provider=gdrive&file_id=fid1")
            assert response.status_code == 200


def test_update_thumbnail_invalid_request(client):
    """Test updating thumbnail with missing parameters."""

    response = client.patch("/files/fid1/thumbnail?provider=gdrive")
    assert response.status_code == 400
    assert response.json()["detail"] == "Missing timestamp or file"


def test_list_files_invalid_json(client, mock_db):
    """Test list_files with invalid JSON folder_id."""
    acc = models.Account(id=1, user_id=1, email="g@gmail.com", provider="gdrive")
    mock_db._query_results[models.Account] = [acc]

    # Use refresh=True to bypass any cache and trigger the JSON check
    response = client.get('/files/?folder_id={"key":}&refresh=true')
    assert response.status_code == 400


def test_stream_file_refresh_retry(client, mock_db):
    """Test stream_file retrying on 401 GDrive."""
    acc = models.Account(
        id=1, user_id=1, email="g@gmail.com", provider="gdrive", access_token="old"
    )
    mock_db._query_results[models.Account] = [acc]

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp_401 = MagicMock()
        mock_resp_401.status_code = 401
        mock_resp_200 = MagicMock()
        mock_resp_200.status_code = 200
        mock_resp_200.aiter_bytes.return_value = _aiter_bytes([b"data"])

        mock_get.side_effect = [mock_resp_401, mock_resp_200]

        with patch("app.api.routes.files.get_valid_access_token", return_value="new"):
            with patch("httpx.AsyncClient.stream") as mock_stream:
                mock_stream_ctx = mock_stream.return_value.__aenter__.return_value
                mock_stream_ctx.status_code = 200
                mock_stream_ctx.headers = {"Content-Length": "100"}
                mock_stream_ctx.aiter_bytes.return_value = _aiter_bytes([b"data"])

                response = client.get("/files/stream?provider=gdrive&file_id=g@gmail.com:f1")
                assert response.status_code == 200


def test_stream_file_connect_error(client, mock_db):
    """Test stream_file handling source connection error."""
    acc = models.Account(id=1, user_id=1, email="g@gmail.com", provider="gdrive")
    mock_db._query_results[models.Account] = [acc]

    with patch("httpx.AsyncClient.stream", side_effect=Exception("Connection refused")):
        response = client.get("/files/stream?provider=gdrive&file_id=g@gmail.com:f1")
        assert response.status_code == 502


def test_get_thumbnail_custom_fail(client, mock_db):
    """Test on-demand thumbnail extraction failure."""
    acc = models.Account(id=1, user_id=1, email="g@gmail.com", provider="gdrive")
    mock_db._query_results[models.Account] = [acc]

    with patch(
        "app.services.thumbnail_service.extract_video_frame", side_effect=Exception("FFmpeg error")
    ):
        with patch("os.path.exists", return_value=False):
            with patch("app.api.routes.files.FileResponse") as mock_resp:
                mock_resp.return_value.status_code = 200
                response = client.get("/files/thumbnail?provider=gdrive&file_id=f1&timestamp=10")
                assert response.status_code == 200


def test_stream_file_mega(client, mock_db):
    """Test streaming a file from MEGA."""
    acc = models.Account(
        id=1,
        user_id=1,
        email="m@mega.nz",
        provider="mega",
        access_token="email",
        refresh_token="pass",
    )
    mock_db._query_results[models.Account] = [acc]

    with patch("httpx.AsyncClient.stream") as mock_stream:
        mock_stream_ctx = mock_stream.return_value.__aenter__.return_value
        mock_stream_ctx.status_code = 200
        mock_stream_ctx.headers = {"Content-Length": "100"}
        mock_stream_ctx.aiter_bytes.return_value = _aiter_bytes([b"data"])

        response = client.get("/files/stream?provider=mega&file_id=m@mega.nz:f1")
        assert response.status_code == 200
        # Check if mega specific headers were prepared (indirectly via status check)


def test_stream_file_range(client, mock_db):
    """Test streaming with Range header."""
    acc = models.Account(id=1, user_id=1, email="g@gmail.com", provider="gdrive")
    mock_db._query_results[models.Account] = [acc]

    with patch("app.api.routes.files.get_valid_access_token", return_value="token"):
        with patch("httpx.AsyncClient.stream") as mock_stream:
            mock_stream_ctx = mock_stream.return_value.__aenter__.return_value
            mock_stream_ctx.status_code = 206
            mock_stream_ctx.headers = {"Content-Range": "bytes 0-99/100"}
            mock_stream_ctx.aiter_bytes.return_value = _aiter_bytes([b"data"])

            response = client.get(
                "/files/stream?provider=gdrive&file_id=f1", headers={"Range": "bytes=0-99"}
            )
            assert response.status_code == 206
            assert response.headers["Content-Range"] == "bytes 0-99/100"


def test_stream_file_streams_chunks_and_forwards_cache_headers(client, mock_db):
    """Test streaming response body and cache-related headers passthrough."""
    acc = models.Account(id=1, user_id=1, email="g@gmail.com", provider="gdrive")
    mock_db._query_results[models.Account] = [acc]

    with patch("app.api.routes.files.get_valid_access_token", return_value="token"):
        with patch("httpx.AsyncClient.stream") as mock_stream:
            header_resp = AsyncMock()
            header_resp.status_code = 206
            header_resp.headers = {
                "Content-Range": "bytes 0-3/4",
                "Content-Length": "4",
                "Cache-Control": "public, max-age=60",
                "ETag": '"abc123"',
                "Last-Modified": "Mon, 01 Jan 2024 00:00:00 GMT",
            }

            body_resp = MagicMock()
            body_resp.status_code = 206
            body_resp.aiter_bytes.return_value = _aiter_bytes([b"ab", b"cd"])

            header_ctx = AsyncMock()
            header_ctx.__aenter__.return_value = header_resp
            body_ctx = AsyncMock()
            body_ctx.__aenter__.return_value = body_resp
            mock_stream.side_effect = [header_ctx, body_ctx]

            response = client.get(
                "/files/stream?provider=gdrive&file_id=f1", headers={"Range": "bytes=0-3"}
            )

            assert response.status_code == 206
            assert response.content == b"abcd"
            assert response.headers["Content-Range"] == "bytes 0-3/4"
            assert response.headers["Cache-Control"] == "public, max-age=60"
            assert response.headers["ETag"] == '"abc123"'
            assert response.headers["Last-Modified"] == "Mon, 01 Jan 2024 00:00:00 GMT"


def test_get_thumbnail_metadata_mismatch(client, mock_db):
    """Test get_thumbnail when metadata exists but file is missing on disk."""
    mock_meta = models.FileMetadata(file_id="f1", thumbnail_path="f1.jpg")
    mock_db._query_results[models.FileMetadata] = [mock_meta]

    with patch("os.path.exists", return_value=False):
        # Should proceed to fire background task and return placeholder
        with patch("app.api.routes.files.FileResponse") as mock_resp:
            mock_resp.return_value.status_code = 200
            response = client.get("/files/thumbnail?provider=gdrive&file_id=f1")
            assert response.status_code == 200
            assert "placeholder" in mock_resp.call_args[0][0]


def test_update_thumbnail_mega(client, mock_db):
    """Test updating MEGA thumbnail via timestamp."""
    acc = models.Account(
        id=1, user_id=1, email="m@mega.nz", provider="mega", access_token="e", refresh_token="p"
    )
    mock_db._query_results[models.Account] = [acc]
    mock_meta = models.FileMetadata(file_id="f1", updated_at=123)
    mock_db._query_results[models.FileMetadata] = [mock_meta]

    with patch("app.services.thumbnail_service.extract_video_frame", return_value=(100, 10, 10)):
        with patch("app.services.thumbnail_service.save_metadata"):
            response = client.patch("/files/f1/thumbnail?provider=mega&timestamp=10")
            assert response.status_code == 200
