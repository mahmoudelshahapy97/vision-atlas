# app/routes/custom_router.py
"""Uploaded (custom) models. The API owns them (database row + file); it pushes
the file here the first time a run uses it. Files are stored by sha256, so a
restart of either side doesn't force another upload."""

import hashlib
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool

from app import ops
from app.core.security import require_token
from app.registry import ULTRA_TASKS, wdir

router = APIRouter(prefix="/v1/custom", tags=["custom models"], dependencies=[Depends(require_token)])

_KEY = re.compile(r"^custom:\d+$")
_MAX_BYTES = 1024 * 1024 * 1024


def _check_key(key: str) -> None:
    if not _KEY.match(key):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Key must look like custom:<id>.")


@router.put("/{key}")
async def push(key: str, request: Request, x_content_sha256: str = Header(...)) -> Dict[str, Any]:
    _check_key(key)
    dest = ops.custom_file(x_content_sha256)
    if not dest.exists():
        tmp = dest.with_name(f"{uuid.uuid4().hex}.part")
        digest, size = hashlib.sha256(), 0
        try:
            with open(tmp, "wb") as f:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > _MAX_BYTES:
                        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Weights larger than 1 GB.")
                    digest.update(chunk)
                    f.write(chunk)
            if digest.hexdigest() != x_content_sha256:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="sha256 doesn't match the body.")
            tmp.replace(dest)
        finally:
            tmp.unlink(missing_ok=True)
    await run_in_threadpool(ops.ensure_custom, key, x_content_sha256)
    return {"key": key, "sha256": x_content_sha256}


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
def forget(key: str, x_content_sha256: str = Header("")) -> Response:
    _check_key(key)
    ops.forget_custom(key)
    if x_content_sha256:
        ops.custom_file(x_content_sha256).unlink(missing_ok=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/inspect")
def inspect(file: UploadFile = File(...)) -> Dict[str, Any]:
    """Task and class names of an Ultralytics .pt, without keeping it."""
    with tempfile.NamedTemporaryFile(suffix=".pt", dir=wdir()) as tmp:
        while chunk := file.file.read(1 << 20):
            tmp.write(chunk)
        tmp.flush()
        try:
            task, names = ops.inspect_weights(Path(tmp.name))
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail=f"That file isn't a loadable Ultralytics model: {e}")
    if task not in ULTRA_TASKS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unsupported model task '{task}'.")
    return {"task": task, "names": names}
