"""File Utilities Module.

Responsibilities:
- Provide helpers for file type detection and metadata extraction

Boundaries:
- Does not handle filesystem I/O directly
"""

import mimetypes


def get_media_type(file_name: str):
    """Detect media type based on file extension."""

    mime, _ = mimetypes.guess_type(file_name)

    if not mime:
        return "application/octet-stream"

    return mime
