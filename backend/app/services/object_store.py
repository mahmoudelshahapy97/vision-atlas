# app/services/object_store.py
"""Images, videos and documents in MinIO (S3-compatible); Postgres keeps the keys and links.

Every key is namespaced by run, so deleting a run removes its files with one
prefix delete:

    runs/<public_id>/in/000-image.jpg      an input the user uploaded or picked
    runs/<public_id>/out/03-mask.png       an output the pipeline wrote

The bucket is private. Browsers load files through presigned GET links, which
are signed for MINIO_PUBLIC_URL (where browsers reach MinIO) rather than the
endpoint the API connects to. MINIO_PUBLIC_URL=/ gives same-origin links
(/<bucket>/<key>?X-Amz-...) that the console's nginx forwards to MinIO, so
browsers need nothing but the console's address. Signing is local: the region
is fixed, so it never asks the server.

Nothing here raises: a failed call logs and returns None/False, and callers
keep the file on disk (served at /media) so an outage of the store never costs
a run. The SDK is blocking, so calls run in threads.
"""

import asyncio
import logging
import mimetypes
import threading
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple
from urllib.parse import urlsplit

from app.core.config import config
from app.utils.upload_utils import media_kind

logger = logging.getLogger(__name__)


def content_type(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def object_kind(name: str) -> str:
    """'image', 'video' or 'document' (CSV, JSON, text, anything else)."""
    return media_kind(name) or "document"


class ObjectStore:
    def __init__(self) -> None:
        self._client = None
        self._signer = None
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return bool(config.minio_endpoint)

    @property
    def bucket(self) -> str:
        return config.minio_bucket

    # ---------------------------------------------------------------- client
    def _connect(self):
        """The client, created (and the bucket ensured) on first use."""
        if self._client is not None:
            return self._client
        with self._lock:
            if self._client is None:
                from minio import Minio

                client = Minio(
                    config.minio_endpoint,
                    access_key=config.minio_access_key,
                    secret_key=config.minio_secret_key,
                    secure=config.minio_secure,
                    region=config.minio_region,
                )
                if not client.bucket_exists(self.bucket):
                    client.make_bucket(self.bucket)
                self._client = client
        return self._client

    @property
    def relative_links(self) -> bool:
        """MINIO_PUBLIC_URL=/ : links are paths on the console's origin, signed for
        MINIO_ENDPOINT, which is the Host the console's proxy sends to MinIO."""
        return config.minio_public_url.strip() == "/"

    def link_base(self) -> str:
        """What every current link to this bucket starts with."""
        if self.relative_links:
            return f"/{self.bucket}/"
        public = config.minio_public_url or f"{'https' if config.minio_secure else 'http'}://{config.minio_endpoint}"
        return f"{public.rstrip('/')}/{self.bucket}/"

    def _signing_client(self):
        """A client for MINIO_PUBLIC_URL, used only to sign links (no network)."""
        if self._signer is not None:
            return self._signer
        with self._lock:
            if self._signer is None:
                from minio import Minio

                public = urlsplit(config.minio_public_url) if config.minio_public_url and not self.relative_links else None
                self._signer = Minio(
                    public.netloc if public else config.minio_endpoint,
                    access_key=config.minio_access_key,
                    secret_key=config.minio_secret_key,
                    secure=public.scheme == "https" if public else config.minio_secure,
                    region=config.minio_region,
                )
        return self._signer

    async def _run(self, what: str, fn, *args):
        if not self.enabled:
            return None
        try:
            return await asyncio.to_thread(fn, *args)
        except Exception as e:
            logger.warning("Object store %s failed: %s", what, e)
            return None

    # ------------------------------------------------------------------ write
    async def put_file(self, key: str, path: str, ctype: str) -> bool:
        def put():
            self._connect().fput_object(self.bucket, key, path, content_type=ctype)
            return True

        return bool(await self._run(f"put {key}", put))

    # ------------------------------------------------------------------ links
    def presign(self, key: str, download_name: Optional[str] = None) -> Optional[Tuple[str, datetime]]:
        """(presigned GET link, its expiry), or None when the store is off.

        With download_name the link makes the browser save the file under that
        name: the download attribute of a cross-origin <a> is ignored.
        """
        if not self.enabled:
            return None
        hours = min(max(config.minio_url_expire_hours, 1), 168)
        expires = timedelta(hours=hours)
        headers = None
        if download_name:
            safe = download_name.replace('"', "").replace("\\", "")
            headers = {"response-content-disposition": f'attachment; filename="{safe}"'}
        try:
            url = self._signing_client().presigned_get_object(
                self.bucket, key, expires=expires, response_headers=headers
            )
        except Exception as e:
            logger.warning("Object store sign %s failed: %s", key, e)
            return None
        if self.relative_links:
            parts = urlsplit(url)
            url = f"{parts.path}?{parts.query}"
        return url, datetime.now(timezone.utc) + expires

    # ----------------------------------------------------------------- delete
    async def list_keys(self, prefix: str) -> List[str]:
        def scan():
            return [
                obj.object_name
                for obj in self._connect().list_objects(self.bucket, prefix=prefix, recursive=True)
            ]

        return await self._run(f"list {prefix}", scan) or []

    async def remove(self, keys: List[str]) -> List[str]:
        """Delete ``keys``; returns the ones actually removed."""
        if not keys:
            return []

        def delete():
            from minio.deleteobjects import DeleteObject

            failed = {
                error.name
                for error in self._connect().remove_objects(
                    self.bucket, [DeleteObject(k) for k in keys]
                )
            }
            return [k for k in keys if k not in failed]

        return await self._run(f"remove {len(keys)} objects", delete) or []

    async def remove_prefix(self, prefix: str) -> int:
        return len(await self.remove(await self.list_keys(prefix)))

    async def healthy(self) -> bool:
        return bool(await self._run("health", lambda: self._connect().bucket_exists(self.bucket)))


object_store = ObjectStore()
