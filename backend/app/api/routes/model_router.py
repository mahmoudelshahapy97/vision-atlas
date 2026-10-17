# app/api/routes/model_router.py
"""Models: built-in public models (status, prefetch) and uploaded weights."""

import logging
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool

from app.api.deps import get_current_user, is_admin, optional_user, require_role
from app.core.config import config
from app.schemas.lab_schemas import CustomModelResponse
from app.services.model_service import model_service
from app.utils.upload_utils import UploadTooLarge, save_upload
from app.vision.registry import ModelError, manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["vision lab"], prefix="/models")

_MAX_WEIGHTS_BYTES = 1024 * 1024 * 1024

# Prefetch state per model key: "downloading", "ready" or "error: ...". In
# memory on purpose: it only describes prefetches this process asked
# models-serve for.
_downloads: Dict[str, str] = {}


@router.get("")
async def list_models(user: Optional[Dict[str, Any]] = Depends(optional_user)) -> Dict[str, Any]:
    try:
        served = await run_in_threadpool(manager.catalog)
    except (ModelError, RuntimeError) as e:
        logger.warning("Model server unavailable: %s", e)
        served = {"models": [], "device": None, "yolo_size": None, "error": str(e)}
    builtin = served["models"]
    for b in builtin:
        b["download_state"] = _downloads.get(b["key"])
    try:
        rows = await model_service.list_visible(user["id"] if user else None)
    except Exception as e:
        logger.error("Error listing models: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not list models.")
    custom = [CustomModelResponse(**m).model_dump() for m in rows]
    return {
        "builtin": builtin,
        "custom": custom,
        "device": served.get("device"),
        "gpu": served.get("gpu"),
        "yolo_size": served.get("yolo_size"),
        "model_server_error": served.get("error"),
    }


@router.post("/{key}/download", status_code=status.HTTP_202_ACCEPTED)
async def download_model(key: str, _: Dict[str, Any] = Depends(require_role("admin"))) -> Dict[str, Any]:
    if key not in await run_in_threadpool(manager.specs):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown model '{key}'.")
    if _downloads.get(key) == "downloading":
        return {"key": key, "state": "downloading"}
    _downloads[key] = "downloading"

    def work() -> None:
        try:
            manager.load(key)  # models-serve downloads (if needed) and loads, which also validates the file
            _downloads[key] = "ready"
        except ModelError as e:
            _downloads[key] = f"error: {e}"
        except Exception as e:
            logger.error("Prefetch of %s failed: %s", key, e, exc_info=True)
            _downloads[key] = f"error: {type(e).__name__}: {e}"

    threading.Thread(target=work, daemon=True).start()
    return {"key": key, "state": "downloading"}


@router.post("/upload", response_model=CustomModelResponse, status_code=status.HTTP_201_CREATED)
async def upload_model(
    file: UploadFile = File(...),
    name: str = Form(...),
    project_id: Optional[int] = Form(None),
    is_public: bool = Form(False),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    if not file.filename or Path(file.filename).suffix.lower() != ".pt":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Upload an Ultralytics .pt weights file (e.g. best.pt from your training run).",
        )
    folder = config.weights_dir / "custom"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{uuid.uuid4().hex}.pt"
    try:
        size = await save_upload(file, path, _MAX_WEIGHTS_BYTES)
    except UploadTooLarge:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Weights larger than 1 GB aren't supported.")
    try:
        # models-serve loads it with Ultralytics and rejects unsupported tasks.
        task, names = await run_in_threadpool(manager.inspect, path)
    except ModelError as e:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception as e:
        path.unlink(missing_ok=True)
        logger.error("Model server couldn't inspect an upload: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="The model server couldn't check the file.")
    try:
        return await model_service.create_model(
            owner_id=current_user["id"],
            project_id=project_id,
            name=name.strip()[:160] or file.filename,
            task=task,
            file_path=str(path),
            classes=names,
            size_bytes=size,
            is_public=bool(is_public and is_admin(current_user)),
        )
    except Exception as e:
        path.unlink(missing_ok=True)
        logger.error("Error saving uploaded model: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not save the model.")


@router.delete("/custom/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(model_id: int, current_user: Dict[str, Any] = Depends(get_current_user)) -> Response:
    m = await model_service.get_model(model_id)
    if not m or (m["owner_id"] != current_user["id"] and not is_admin(current_user)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found.")
    try:
        Path(m["file_path"]).unlink(missing_ok=True)
        await run_in_threadpool(manager.forget_custom, f"custom:{model_id}")
        await model_service.delete_model(model_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        logger.error("Error deleting model %s: %s", model_id, e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not delete the model.")
