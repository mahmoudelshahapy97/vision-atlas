# app/utils/upload_utils.py
"""Streaming uploads to disk with a size cap, and media type detection."""

from pathlib import Path
from typing import Optional

from fastapi import UploadFile

from app.vision.core import IMAGE_EXT, VIDEO_EXT

_CHUNK = 1 << 20


class UploadTooLarge(Exception):
    """The upload passed its byte limit; the partial file has been removed."""


def media_kind(filename: str) -> Optional[str]:
    """'image', 'video', or None for anything the lab can't read."""
    ext = Path(filename).suffix.lower()
    return "image" if ext in IMAGE_EXT else "video" if ext in VIDEO_EXT else None


async def save_upload(upload: UploadFile, dest: Path, limit_bytes: int) -> int:
    """Write the upload to dest in 1 MB chunks and return its size.

    Raises UploadTooLarge (after deleting the partial file) once the limit is
    passed, so a huge upload never fills the disk.
    """
    size = 0
    with open(dest, "wb") as f:
        while chunk := await upload.read(_CHUNK):
            size += len(chunk)
            if size > limit_bytes:
                f.close()
                dest.unlink(missing_ok=True)
                raise UploadTooLarge(upload.filename)
            f.write(chunk)
    return size
