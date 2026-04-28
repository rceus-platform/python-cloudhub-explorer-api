"""Thumbnail Service Module.

Responsibilities:
- Extract frames from video streams using FFmpeg
- Process and optimize image files using Pillow
- Manage thumbnail cache and metadata persistence

Boundaries:
- Does not handle provider-specific streaming URLs
- Does not handle HTTP responses (delegated to route handlers)
"""

import io
import logging
import os
import time

import ffmpeg  # type: ignore[import]
import requests
from PIL import Image, ImageOps
from sqlalchemy.orm import Session

from app.db import models

logger = logging.getLogger(__name__)


def get_cache_path(file_id: str, timestamp: int | None = None) -> str:
    """Generate a unique filesystem path for a thumbnail or preview."""

    cache_dir = os.path.abspath(os.path.join(os.getcwd(), "../../cache/thumbnails"))
    os.makedirs(cache_dir, exist_ok=True)

    if timestamp is not None:
        return os.path.join(cache_dir, f"preview_{file_id}_{timestamp}.jpg")
    return os.path.join(cache_dir, f"{file_id}.jpg")


def process_image_thumbnail(
    stream_url: str, headers: dict[str, str], cache_path: str
) -> tuple[int, int]:
    """Download, rotate, and resize an image for use as a thumbnail."""

    resp = requests.get(stream_url, headers=headers, timeout=30)
    if resp.status_code >= 400:
        logger.error(
            "Thumbnail request to %s failed with %d: %s",
            stream_url, resp.status_code, resp.text
        )
    resp.raise_for_status()

    img = Image.open(io.BytesIO(resp.content))
    img = ImageOps.exif_transpose(img)

    orig_width, orig_height = img.size
    if orig_width > 800:
        new_width = 800
        new_height = int(orig_height * (800 / orig_width))
        img = img.resize(
            (new_width, new_height), Image.Resampling.LANCZOS
        )  # type: ignore[return-value]

    img.convert("RGB").save(cache_path, "JPEG", quality=75, optimize=True)
    return img.size


def extract_video_frame(
    stream_url: str,
    headers: dict[str, str],
    cache_path: str,
    timestamp: int | None = None,
) -> tuple[float | None, int | None, int | None]:
    """Extract a single frame from a video stream using FFmpeg 8.1 compatible filters."""

    seek_time = f"{timestamp}" if timestamp is not None else "60"
    input_args = {"ss": seek_time}
    # Ensure headers is a dictionary
    if headers and isinstance(headers, dict):
        header_str = "".join([f"{k}: {v}\r\n" for k, v in headers.items()])
        input_args["headers"] = header_str

    # Metadata extraction
    duration, width, height = None, None, None
    if timestamp is None:
        probe_args = {}
        if headers and isinstance(headers, dict):
            header_str = "".join([f"{k}: {v}\r\n" for k, v in headers.items()])
            probe_args["headers"] = header_str

        try:
            probe = ffmpeg.probe(stream_url, **probe_args)  # type: ignore[no-untyped-call]
            video_stream = next(
                (s for s in probe["streams"] if s["codec_type"] == "video"), None
            )
            duration = float(probe["format"]["duration"])
            width = int(video_stream["width"]) if video_stream else None
            height = int(video_stream["height"]) if video_stream else None
        except Exception as e:
            logger.error("ffprobe failed: %s", e)

    # Frame extraction
    (
        ffmpeg.input(stream_url, threads=1, **input_args)  # type: ignore[no-untyped-call]
        .filter(  # type: ignore[no-untyped-call]
            "setparams", color_primaries="bt709", color_trc="bt709", colorspace="bt709"
        )
        .output(  # type: ignore[no-untyped-call]
            cache_path, vframes=1, vcodec="mjpeg", format="image2", **{"qscale:v": 4}
        )
        .overwrite_output()  # type: ignore[no-untyped-call]
        .run(capture_stdout=True, capture_stderr=True)  # type: ignore[no-untyped-call]
    )

    return duration, width, height


def save_metadata(
    db: Session,
    file_id: str,
    provider: str,
    name: str | None,
    duration: float | None,
    width: int | None,
    height: int | None,
):
    """Update or create file metadata in the database."""

    metadata = (
        db.query(models.FileMetadata)
        .filter(models.FileMetadata.file_id == file_id)
        .first()
    )
    if not metadata:
        metadata = models.FileMetadata(file_id=file_id, provider=provider)
        db.add(metadata)

    if name:
        metadata.name = name  # type: ignore[attr-defined]

    metadata.thumbnail_path = f"{file_id}.jpg"  # type: ignore[attr-defined]
    if duration and duration > 0:
        metadata.duration = str(int(duration))  # type: ignore[attr-defined]
    metadata.width = width  # type: ignore[attr-defined]
    metadata.height = height  # type: ignore[attr-defined]
    metadata.updated_at = int(time.time())  # type: ignore[attr-defined]
    db.commit()
