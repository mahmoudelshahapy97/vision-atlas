# app/main.py
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import config
from app.core.database import (
    check_postgres_health,
    close_db_pool,
    ensure_schema_upgrades,
    get_pool,
    init_db_pool,
    wait_for_schema,
)
from app.core.logging_config import setup_logging
from app.services.object_store import object_store
from app.services.run_service import run_service
from app.services.event_service import event_service, wait_for_uploads
from app.services.stream_manager import stream_manager
from app.services.user_service import user_service
from app.vision import runner
from app.vision.registry import manager

setup_logging(config.log_file_path)
logger = logging.getLogger(__name__)

SAMPLES_DIR = Path(__file__).parent / "vision" / "samples"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s v%s (%s)", config.app_name, config.app_version, config.environment)
    config.media_dir.mkdir(parents=True, exist_ok=True)
    config.weights_dir.mkdir(parents=True, exist_ok=True)

    try:
        await init_db_pool()
    except Exception as e:
        logger.critical("Database pool initialization failed: %s", e, exc_info=True)
        raise RuntimeError("Database pool initialization failed.") from e

    if not await check_postgres_health():
        logger.warning("Database health check failed at startup.")

    schema_ready = await wait_for_schema()
    if schema_ready:
        try:
            await ensure_schema_upgrades()
        except Exception as e:
            logger.error("Schema upgrade failed: %s", e, exc_info=True)

        try:
            await user_service.ensure_bootstrap_admin()
        except Exception as e:
            logger.error("Could not ensure bootstrap admin: %s", e, exc_info=True)

        try:
            if n := await run_service.recover_interrupted():
                logger.info("Marked %d interrupted runs as failed", n)
        except Exception as e:
            logger.error("Could not recover interrupted runs: %s", e, exc_info=True)
    else:
        logger.warning("Schema not ready; bootstrap admin and run recovery were skipped.")

    if not object_store.enabled:
        logger.info("Object store disabled (MINIO_ENDPOINT is empty); run files stay in %s.", config.media_dir)
    elif await object_store.healthy():
        logger.info("Object store ready: MinIO %s, bucket %s.", config.minio_endpoint, object_store.bucket)
    else:
        logger.warning("MinIO at %s is unreachable; run files stay on disk until it is back.", config.minio_endpoint)

    runner.start(asyncio.get_running_loop())
    stream_manager.on_output = event_service.record_output  # live analyzers' events -> camera_event
    try:
        await stream_manager.startup()  # resumes enabled cameras, then supervises them
    except Exception as e:
        logger.error("Could not start camera workers: %s", e, exc_info=True)
    purge = asyncio.create_task(event_service.purge_forever(), name="event-retention")
    logger.info("Startup complete.")
    yield

    logger.info("Shutdown sequence initiated...")
    await stream_manager.shutdown()
    purge.cancel()
    await wait_for_uploads(timeout=10)
    runner.stop()

    try:
        await close_db_pool()
    except Exception as e:
        logger.error("Error closing database pool: %s", e, exc_info=True)

    logger.info("Shutdown complete.")


app = FastAPI(
    lifespan=lifespan,
    title=config.app_name,
    description=config.app_description,
    version=config.app_version,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=config.cors_allow_credentials,
    allow_methods=config.cors_allow_methods,
    allow_headers=config.cors_allow_headers,
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if "server" in response.headers:
        del response.headers["server"]
    return response


@app.get("/health", tags=["system"])
async def health_check():
    """Health probe with database, model-server and object-store diagnostics
    (used by the container healthcheck). The model server or MinIO being down
    doesn't make the API unhealthy: the catalog and run history still work."""
    pool = get_pool()
    db_healthy = await check_postgres_health()
    models = await run_in_threadpool(manager.health)
    store_ok = await object_store.healthy() if object_store.enabled else False

    pool_stats = None
    if pool is not None and not pool._closed:
        pool_stats = {
            "size": pool.get_size(),
            "idle": pool.get_idle_size(),
            "max": pool.get_max_size(),
        }

    return {
        "status": "healthy" if db_healthy else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": config.app_version,
        "db_connection_ok": db_healthy,
        "pool_stats": pool_stats,
        "models": {
            "url": config.models_url,
            "ok": models is not None,
            "device": (models or {}).get("device"),
            "gpu": (models or {}).get("gpu"),
        },
        "object_store": {
            "backend": "minio" if object_store.enabled else "disk",
            "bucket": object_store.bucket if object_store.enabled else None,
            "ok": store_ok,
        },
        "lab_workers": config.lab_workers,
    }


@app.get(f"{config.app_api_prefix}/health", tags=["system"])
async def api_health():
    """The original console probe, kept for existing clients."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.fetchval("SELECT 1")
    models = await run_in_threadpool(manager.health)
    return {"status": "ok", "database": "postgresql", "device": (models or {}).get("device")}


app.include_router(router)

# Lab samples are plain files ("/api/lab/samples/..."). Run files are in MinIO
# behind presigned links; /media serves the ones kept on disk (MinIO off or
# unreachable when the run ended, and runs from before MinIO).
config.media_dir.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=config.media_dir), name="media")
app.mount(f"{config.app_api_prefix}/lab/samples", StaticFiles(directory=SAMPLES_DIR), name="samples")


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=config.app_host,
        port=config.app_port,
        log_level=config.log_level.lower(),
    )
