"""File utilities: helper functions for MIME type detection and file handling."""


import mimetypes


def get_media_type(file_name: str):
    """
    Detect media type based on file extension
    """

    mime, _ = mimetypes.guess_type(file_name)

    if not mime:
        return "application/octet-stream"

    return mime
