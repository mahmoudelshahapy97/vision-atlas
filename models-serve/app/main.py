# app/main.py
"""models-serve: every Vision Lab model behind one HTTP API.

The Atlas API runs the pipelines (OpenCV, video, drawing) and calls this
service for each model step, so this process can sit on a GPU host of its own.
Run a single worker: the loaded models and tracking sessions live in memory.
"""
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.codec import InputError
from app.core.config import config
from app.core.logging_config import setup_logging
from app.ops import CustomMissing
from app.registry import ModelError, manager, wdir
from app.routes import custom_router, infer_router, models_router

setup_logging()
logger = logging.getLogger(__name__)


def _preload() -> None:
    for key in config.preload:
        try:
            models_router.load_model(key)
            logger.info("Preloaded %s", key)
        except Exception as e:
            logger.warning("Preload of %s failed: %s", key, e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    wdir()
    info = models_router.device_info()
    logger.info("Starting %s v%s on %s (cuda available: %s, gpu: %s)", config.app_name, config.app_version,
                config.device, info["cuda"], info["gpu"])
    if config.device.startswith("cuda") and not info["cuda"]:
        logger.warning("DEVICE=%s but CUDA isn't available; models will run on the CPU.", config.device)
    if config.preload:
        # In the background, so /health answers while the weights download.
        threading.Thread(target=_preload, name="preload", daemon=True).start()
    yield


app = FastAPI(lifespan=lifespan, title=config.app_name, version=config.app_version)


@app.exception_handler(ModelError)
async def model_error(_: Request, e: ModelError):
    return JSONResponse(status_code=503, content={"detail": str(e), "error": "model"})


@app.exception_handler(InputError)
async def input_error(_: Request, e: InputError):
    return JSONResponse(status_code=400, content={"detail": str(e), "error": "input"})


@app.exception_handler(CustomMissing)
async def custom_missing(_: Request, e: CustomMissing):
    return JSONResponse(status_code=409, content={"detail": str(e), "error": "custom_missing"})


@app.exception_handler(Exception)
async def unexpected(_: Request, e: Exception):
    logger.error("Unhandled error: %s", e, exc_info=e)
    return JSONResponse(status_code=500, content={"detail": f"{type(e).__name__}: {e}", "error": "internal"})


@app.get("/health", tags=["system"])
def health():
    """Unauthenticated: device and what's in memory, no model names from users."""
    return {"status": "ok", "version": config.app_version, **models_router.device_info(),
            "yolo_size": config.yolo_size, "loaded": sorted(k for k in manager._cache if not k.startswith("custom:"))}


app.include_router(models_router.router)
app.include_router(infer_router.router)
app.include_router(custom_router.router)
