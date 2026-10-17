# app/scripts/migrate_media_to_minio.py
"""Move the files of finished runs from MEDIA_DIR to MinIO.

Runs from before the object store (or that ended while MinIO was down) still
link to /media/runs/... files on disk. This uploads them, saves their
media_object rows and links, and removes a run's local folder once all of its
files are in the store. Safe to re-run: stored files are skipped.

    docker compose exec api python -m app.scripts.migrate_media_to_minio
"""

import asyncio
import logging

from app.core.database import close_db_pool, db_manager, ensure_schema_upgrades, init_db_pool
from app.core.logging_config import setup_logging
from app.services.media_service import all_stored, media_service
from app.services.object_store import object_store
from app.vision import runner

logger = logging.getLogger("atlas.migrate_media")


async def main() -> None:
    if not object_store.enabled:
        raise SystemExit("MINIO_ENDPOINT is not set; nothing to migrate to.")
    if not await object_store.healthy():
        raise SystemExit("MinIO is unreachable.")
    await init_db_pool()
    try:
        await ensure_schema_upgrades()
        runs = await db_manager.execute_query(
            "SELECT id, public_id, inputs, result FROM inference_run WHERE status IN ('done', 'error') ORDER BY id",
            fetch_all=True,
        )
        moved = left = 0
        for run in runs:
            if all_stored(run["inputs"], run["result"]):
                continue
            await media_service.store_run_files(run["id"], run["inputs"], run["result"])
            await db_manager.execute_query(
                "UPDATE inference_run SET inputs = $2, result = $3 WHERE id = $1",
                (run["id"], run["inputs"], run["result"]),
            )
            if all_stored(run["inputs"], run["result"]):
                runner.delete_files(run["public_id"])
                moved += 1
            else:
                logger.warning("Run %s: some files are missing or failed to upload; kept on disk.", run["public_id"])
                left += 1
        logger.info("Moved %d runs to MinIO; %d still have files on disk.", moved, left)
    finally:
        await close_db_pool()


if __name__ == "__main__":
    setup_logging("")
    asyncio.run(main())
