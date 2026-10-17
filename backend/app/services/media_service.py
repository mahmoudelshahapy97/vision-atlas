# app/services/media_service.py
"""A run's files in MinIO, and their links in media_object.

Pipelines and uploads write to the local scratch folder MEDIA_DIR/runs/<id>/
and refer to each file by its "/media/runs/<id>/..." URL. store_run_files()
uploads those files, saves one media_object row per file (key + presigned
link) and swaps the URL in the run's JSON for the link, adding the object key
next to it. sign_runs() puts current links into runs on their way out,
re-signing (and saving) any that are about to expire.

A file that could not be uploaded keeps its /media URL and stays on disk.
"""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from app.core.config import config
from app.core.database import db_manager
from app.services.object_store import content_type, object_kind, object_store

logger = logging.getLogger(__name__)

_LOCAL_PREFIX = "/media/"
_RESIGN_MARGIN = timedelta(hours=1)

# (dict holding the link, URL field, key field)
Ref = Tuple[Dict[str, Any], str, str]


def file_refs(inputs: Optional[List[Dict[str, Any]]], result: Optional[Dict[str, Any]]) -> Iterator[Ref]:
    """Every place a run's JSON links to one of its files."""
    for entry in inputs or []:
        yield entry, "url", "key"
    if not result:
        return
    for entry in (result.get("images") or []) + (result.get("files") or []):
        yield entry, "url", "key"
    video = result.get("video")
    if video:
        yield video, "url", "key"
        if video.get("poster"):
            yield video, "poster", "poster_key"


def all_stored(inputs: Optional[List[Dict[str, Any]]], result: Optional[Dict[str, Any]]) -> bool:
    """True when no link still points at the local scratch folder."""
    return not any(
        str(holder.get(field) or "").startswith(_LOCAL_PREFIX)
        for holder, field, _ in file_refs(inputs, result)
    )


class MediaService:
    def __init__(self) -> None:
        self.db_manager = db_manager

    async def store_run_files(
        self,
        run_id: int,
        inputs: Optional[List[Dict[str, Any]]],
        result: Optional[Dict[str, Any]],
    ) -> bool:
        """Upload the local files the JSON links to and record them; edits inputs/result in place.

        Returns True when every file is in the store.
        """
        if not object_store.enabled:
            return False
        done: Dict[str, str] = {}  # key -> link; a file can be linked twice
        ok = True
        for holder, field, key_field in file_refs(inputs, result):
            url = holder.get(field)
            if not isinstance(url, str) or not url.startswith(_LOCAL_PREFIX):
                continue
            key = url[len(_LOCAL_PREFIX):]
            if key not in done:
                stored = await self._store_one(run_id, key, holder.get("name"))
                if stored is None:
                    ok = False
                    continue
                done[key] = stored
            holder[key_field] = key
            holder[field] = done[key]
        return ok

    async def _store_one(self, run_id: int, key: str, name: Optional[str]) -> Optional[str]:
        path = (config.media_dir / key).resolve()
        if not path.is_relative_to(config.media_dir.resolve()) or not path.is_file():
            logger.warning("Run %s links to %s, which isn't on disk.", run_id, key)
            return None
        name = name or Path(key).name
        kind = object_kind(key)
        ctype = content_type(key)
        if not await object_store.put_file(key, str(path), ctype):
            return None
        signed = object_store.presign(key, name if kind == "document" else None)
        if signed is None:
            return None
        url, expires_at = signed
        await self.db_manager.execute_query(
            """
            INSERT INTO media_object (run_id, bucket, object_key, name, kind, content_type, size_bytes, url, url_expires_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (object_key) DO UPDATE
            SET name = EXCLUDED.name, size_bytes = EXCLUDED.size_bytes,
                url = EXCLUDED.url, url_expires_at = EXCLUDED.url_expires_at
            """,
            (run_id, object_store.bucket, key, name, kind, ctype, path.stat().st_size, url, expires_at),
        )
        return url

    async def sign_runs(self, runs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Put the current link of every stored file into the runs (in place).

        Links that expire within the hour, or were signed for another
        MINIO_PUBLIC_URL, are re-signed first and saved, so what a client
        receives is always good for at least an hour.
        """
        ids = [r["id"] for r in runs if any(h.get(k) for h, _, k in file_refs(r.get("inputs"), r.get("result")))]
        if not ids:
            return runs
        rows = await self.db_manager.execute_query(
            "SELECT object_key, name, kind, url, url_expires_at FROM media_object WHERE run_id = ANY($1::int[])",
            (ids,),
            fetch_all=True,
        )
        links = {row["object_key"]: row["url"] for row in rows}
        soon = datetime.now(timezone.utc) + _RESIGN_MARGIN
        renewed: List[Tuple[str, str, datetime]] = []
        base = object_store.link_base()
        for row in rows:
            if row["url_expires_at"] > soon and row["url"].startswith(base):
                continue
            signed = object_store.presign(row["object_key"], row["name"] if row["kind"] == "document" else None)
            if signed:
                links[row["object_key"]] = signed[0]
                renewed.append((row["object_key"], *signed))
        if renewed:
            await self.db_manager.execute_query(
                """
                UPDATE media_object m
                SET url = v.url, url_expires_at = v.expires_at
                FROM unnest($1::text[], $2::text[], $3::timestamptz[]) AS v (object_key, url, expires_at)
                WHERE m.object_key = v.object_key
                """,
                ([k for k, _, _ in renewed], [u for _, u, _ in renewed], [e for _, _, e in renewed]),
            )
        for run in runs:
            for holder, field, key_field in file_refs(run.get("inputs"), run.get("result")):
                link = links.get(holder.get(key_field))
                if link:
                    holder[field] = link
        return runs

    async def sign_run(self, run: Dict[str, Any]) -> Dict[str, Any]:
        return (await self.sign_runs([run]))[0]

    async def delete_run_files(self, public_id: str) -> None:
        """Remove the run's objects; its media_object rows go with the run (ON DELETE CASCADE)."""
        await object_store.remove_prefix(f"runs/{public_id}/")


media_service = MediaService()
