# app/services/event_service.py
"""Camera events: recorded from the live analyzers' output, listed and
handled by operators, pushed to browsers, and purged after
EVENT_RETENTION_DAYS. Each event keeps one annotated snapshot, stored like a
lab run's files: in MinIO with a presigned link in media_object, or under
MEDIA_DIR (served at /media) without MinIO."""

import asyncio
import logging
import shutil
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

from app.core.config import config
from app.core.database import db_manager
from app.services.alert_hub import alert_hub
from app.services.object_store import object_store
from app.services.stream_manager import encode_jpeg

logger = logging.getLogger(__name__)

_RESIGN_MARGIN = timedelta(hours=1)
EVENT_STATUSES = ("open", "acknowledged", "resolved", "false_positive")

_SELECT = """
    SELECT e.*, c.name AS camera_name, u.name AS handled_by_name,
           m.url AS snapshot_url, m.url_expires_at AS snapshot_expires_at
    FROM camera_event e
    JOIN camera c ON c.id = e.camera_id
    LEFT JOIN app_user u ON u.id = e.handled_by
    LEFT JOIN media_object m ON m.event_id = e.id
"""

# Snapshot uploads outlive the worker step that started them; asyncio keeps
# only weak references to tasks, so this set holds them until they finish.
_uploads: Set[asyncio.Task] = set()


class EventService:
    def __init__(self) -> None:
        self.db_manager = db_manager

    # ------------------------------------------------------------- recording

    async def record_output(self, worker, out, frame: np.ndarray) -> None:
        """The stream manager's on_output hook: store the frame's events."""
        for ev in out.events:
            await self.record(worker, ev, out.frame)

    async def record(self, worker, ev, annotated: np.ndarray) -> Dict[str, Any]:
        row = await self.db_manager.execute_query(
            """
            INSERT INTO camera_event (workspace_id, camera_id, pipeline, kind, label, severity, track_id, confidence, data)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING *
            """,
            (worker.workspace_id, worker.camera_id, worker.pipeline, ev.kind, ev.label, ev.severity, ev.track_id,
             ev.confidence, ev.data or {}),
            fetch_one=True,
        )
        row["camera_name"] = worker.name
        alert_hub.publish(worker.workspace_id, {"type": "event", "event": _jsonable(row)})
        task = asyncio.create_task(self._store_snapshot(row["id"], worker.camera_id, annotated))
        _uploads.add(task)
        task.add_done_callback(_uploads.discard)
        return row

    async def _store_snapshot(self, event_id: int, camera_id: int, annotated: np.ndarray) -> None:
        key = f"events/{camera_id}/{event_id}.jpg"
        path = config.media_dir / key
        try:
            jpeg = await asyncio.to_thread(encode_jpeg, annotated, config.event_snapshot_quality)
            path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(path.write_bytes, jpeg)
            if object_store.enabled and await object_store.put_file(key, str(path), "image/jpeg"):
                signed = object_store.presign(key)
                if signed:
                    await self.db_manager.execute_query(
                        """
                        INSERT INTO media_object (event_id, bucket, object_key, name, kind, content_type, size_bytes, url, url_expires_at)
                        VALUES ($1, $2, $3, $4, 'image', 'image/jpeg', $5, $6, $7)
                        ON CONFLICT (object_key) DO NOTHING
                        """,
                        (event_id, object_store.bucket, key, f"event-{event_id}.jpg", len(jpeg), *signed),
                    )
                    path.unlink(missing_ok=True)
            await self.db_manager.execute_query(
                "UPDATE camera_event SET snapshot_key = $2 WHERE id = $1", (event_id, key)
            )
        except Exception as e:
            logger.warning("Couldn't store the snapshot of event %s: %s", event_id, e)

    # ---------------------------------------------------------------- reading

    async def list(
        self,
        workspace_id: int,
        camera_id: Optional[int] = None,
        kind: Optional[str] = None,
        status: Optional[str] = None,
        severity: Optional[str] = None,
        since: Optional[datetime] = None,
        page: int = 1,
        per_page: int = 50,
    ) -> Tuple[List[Dict[str, Any]], int]:
        where, params = ["e.workspace_id = $1"], [workspace_id]
        for col, val in (("e.camera_id", camera_id), ("e.kind", kind), ("e.status", status), ("e.severity", severity)):
            if val is not None:
                params.append(val)
                where.append(f"{col} = ${len(params)}")
        if since is not None:
            params.append(since)
            where.append(f"e.occurred_at >= ${len(params)}")
        clause = " AND ".join(where)
        total = await self.db_manager.fetch_value(f"SELECT COUNT(*) FROM camera_event e WHERE {clause}", tuple(params))
        params += [per_page, (page - 1) * per_page]
        rows = await self.db_manager.execute_query(
            f"{_SELECT} WHERE {clause} ORDER BY e.occurred_at DESC, e.id DESC "
            f"LIMIT ${len(params) - 1} OFFSET ${len(params)}",
            tuple(params),
            fetch_all=True,
        )
        return await self.sign(rows), total

    async def get(self, event_id: int, workspace_id: int) -> Optional[Dict[str, Any]]:
        row = await self.db_manager.execute_query(
            f"{_SELECT} WHERE e.id = $1 AND e.workspace_id = $2", (event_id, workspace_id), fetch_one=True
        )
        return (await self.sign([row]))[0] if row else None

    async def set_status(self, event_id: int, workspace_id: int, status: str, user_id: int) -> Optional[Dict[str, Any]]:
        done = await self.db_manager.execute_query(
            """
            UPDATE camera_event
            SET status = $3::text,
                handled_by = CASE WHEN $3::text = 'open' THEN NULL ELSE $4::int END,
                handled_at = CASE WHEN $3::text = 'open' THEN NULL ELSE NOW() END
            WHERE id = $1 AND workspace_id = $2
            """,
            (event_id, workspace_id, status, user_id),
            return_rowcount=True,
        )
        return await self.get(event_id, workspace_id) if done else None

    async def stats(self, workspace_id: int) -> Dict[str, Any]:
        return await self.db_manager.execute_query(
            """
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE status = 'open') AS open,
                   COUNT(*) FILTER (WHERE status = 'open' AND severity = 'critical') AS open_critical,
                   COUNT(*) FILTER (WHERE occurred_at >= NOW() - INTERVAL '24 hours') AS last_24h,
                   MAX(occurred_at) AS last_event_at
            FROM camera_event WHERE workspace_id = $1
            """,
            (workspace_id,),
            fetch_one=True,
        )

    async def kinds(self, workspace_id: int) -> List[str]:
        rows = await self.db_manager.execute_query(
            "SELECT DISTINCT kind FROM camera_event WHERE workspace_id = $1 ORDER BY kind", (workspace_id,), fetch_all=True
        )
        return [r["kind"] for r in rows]

    async def sign(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Give every event a working snapshot link: re-sign MinIO links that
        expire within the hour (and save them), or point at /media without MinIO."""
        soon = datetime.now(timezone.utc) + _RESIGN_MARGIN
        base = object_store.link_base() if object_store.enabled else ""
        renewed = []
        for r in rows:
            if r.get("snapshot_url"):
                if r["snapshot_expires_at"] <= soon or not r["snapshot_url"].startswith(base):
                    signed = object_store.presign(r["snapshot_key"])
                    if signed:
                        r["snapshot_url"] = signed[0]
                        renewed.append((r["snapshot_key"], *signed))
            elif r.get("snapshot_key") and (config.media_dir / r["snapshot_key"]).is_file():
                r["snapshot_url"] = f"/media/{r['snapshot_key']}"
            r.pop("snapshot_expires_at", None)
        if renewed:
            await self.db_manager.execute_query(
                """
                UPDATE media_object m SET url = v.url, url_expires_at = v.expires_at
                FROM unnest($1::text[], $2::text[], $3::timestamptz[]) AS v (object_key, url, expires_at)
                WHERE m.object_key = v.object_key
                """,
                ([k for k, _, _ in renewed], [u for _, u, _ in renewed], [e for _, _, e in renewed]),
            )
        return rows

    # -------------------------------------------------------------- retention

    async def purge(self, older_than_days: Optional[int] = None) -> int:
        """Delete events older than the retention period, with their snapshots."""
        days = older_than_days if older_than_days is not None else config.event_retention_days
        rows = await self.db_manager.execute_query(
            "DELETE FROM camera_event WHERE occurred_at < NOW() - make_interval(days => $1) RETURNING snapshot_key",
            (days,),
            fetch_all=True,
        )
        keys = [r["snapshot_key"] for r in rows if r["snapshot_key"]]
        if keys:
            await object_store.remove(keys)
            for k in keys:
                (config.media_dir / k).unlink(missing_ok=True)
        if rows:
            logger.info("Purged %s camera events older than %s days.", len(rows), days)
        return len(rows)

    async def purge_forever(self) -> None:
        """Daily retention loop, started with the camera workers: events, and
        the per-minute metrics behind the analytics charts."""
        from app.services.metric_service import metric_service

        while True:
            try:
                await self.purge()
                await metric_service.purge(config.metric_retention_days)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("Event purge failed: %s", e)
            await asyncio.sleep(24 * 3600)


async def remove_camera_files(camera_id: int) -> None:
    """Event snapshots of a deleted camera (its rows went with it)."""
    await object_store.remove_prefix(f"events/{camera_id}/")
    folder = config.media_dir / "events" / str(camera_id)
    if folder.is_dir():
        await asyncio.to_thread(shutil.rmtree, folder, True)


async def wait_for_uploads(timeout: float) -> None:
    if _uploads:
        await asyncio.wait(set(_uploads), timeout=timeout)


def _jsonable(row: Dict[str, Any]) -> Dict[str, Any]:
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in row.items()}


event_service = EventService()
