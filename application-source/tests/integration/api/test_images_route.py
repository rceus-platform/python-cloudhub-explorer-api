"""Integration tests for images route."""

import io
from unittest.mock import AsyncMock, MagicMock, patch

from PIL import Image

from app.db import models


async def _aiter_bytes(chunks):
    for chunk in chunks:
        yield chunk


def test_get_image_unauthorized(client, mock_db):
    mock_db._query_results[models.Account] = []

    response = client.get("/images/fid1?provider=gdrive&file_name=test.jpg")
    assert response.status_code == 404


def test_get_image_stream_success(client, mock_db):
    acc = models.Account(id=1, user_id=1, email="test@gdrive.com", provider="gdrive", access_token="t1")
    mock_db._query_results[models.Account] = [acc]

    with patch("app.api.routes.images.get_valid_access_token", return_value="token"):
        with patch("httpx.AsyncClient.stream") as mock_stream:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.aiter_bytes.return_value = _aiter_bytes([b"abc"])

            mock_ctx = AsyncMock()
            mock_ctx.__aenter__.return_value = mock_resp
            mock_stream.return_value = mock_ctx

            response = client.get("/images/test@gdrive.com:fid1?provider=gdrive&file_name=test.jpg")
            assert response.status_code == 200
            assert response.content == b"abc"


def test_get_image_resize_success(client, mock_db):
    acc = models.Account(id=1, user_id=1, email="test@gdrive.com", provider="gdrive", access_token="t1")
    mock_db._query_results[models.Account] = [acc]

    img = Image.new("RGB", (120, 80), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    payload = buf.getvalue()

    with patch("app.api.routes.images.get_valid_access_token", return_value="token"):
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = payload
            mock_get.return_value = mock_resp

            response = client.get("/images/fid1?provider=gdrive&file_name=test.jpg&w=40&h=40")
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("image/jpeg")
