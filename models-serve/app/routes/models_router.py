# app/routes/models_router.py
"""The public model catalog: status, load (download + warm up) and raw files."""

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from app.core.config import config
from app.core.security import require_token
from app.registry import SPECS, manager
from app.sessions import sessions

router = APIRouter(prefix="/v1/models", tags=["models"], dependencies=[Depends(require_token)])

# Kinds whose weights are one plain file the API may download (yunet/sface run
# with OpenCV on the API host; the tests also fetch yolo26n.pt this way).
FILE_KINDS = {"ultralytics", "hf", "sam", "url", "colorization", "yoloe"}


def device_info() -> Dict[str, Any]:
    info: Dict[str, Any] = {"device": config.device, "cuda": False, "gpu": None}
    try:
        import torch

        info["cuda"] = torch.cuda.is_available()
        if info["cuda"] and config.device.startswith("cuda"):
            info["gpu"] = torch.cuda.get_device_name(torch.device(config.device))
    except Exception:  # torch missing or broken driver: report CPU
        pass
    return info


@router.get("")
def list_models() -> Dict[str, Any]:
    return {**device_info(), "yolo_size": config.yolo_size, "track_sessions": sessions.count(), "models": manager.status()}


@router.post("/{key}/load")
def load_model(key: str) -> Dict[str, Any]:
    """Download if needed and load into memory (also validates the file)."""
    if key not in SPECS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown model '{key}'.")
    if key == "easyocr":
        manager.get(key, ("ar", "en"))
        manager.get(key, ("en",))
    else:
        manager.get(key)
    return {"key": key, "loaded": True}


@router.get("/{key}/file")
def model_file(key: str) -> FileResponse:
    spec = SPECS.get(key)
    if spec is None or spec.kind not in FILE_KINDS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No single weights file for '{key}'.")
    path = manager.fetch(key)
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")
