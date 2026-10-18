# app/services/alert_hub.py
"""Fan-out of new camera events to the browsers of a workspace (ported from
no-entry-zone's AlertHub). In memory, so it reaches the viewers connected to
this API process, which is the only one (replicas: 1)."""

import asyncio
import logging
from collections import defaultdict
from typing import Any, Dict, Set

logger = logging.getLogger(__name__)

_QUEUE_SIZE = 100


class AlertHub:
    def __init__(self) -> None:
        self._subs: Dict[int, Set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, workspace_id: int) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_SIZE)
        self._subs[workspace_id].add(q)
        return q

    def unsubscribe(self, workspace_id: int, q: asyncio.Queue) -> None:
        self._subs[workspace_id].discard(q)
        if not self._subs[workspace_id]:
            self._subs.pop(workspace_id, None)

    def publish(self, workspace_id: int, message: Dict[str, Any]) -> None:
        """Never blocks: a viewer too slow to keep up loses its oldest alert."""
        for q in list(self._subs.get(workspace_id, ())):
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(message)

    def count(self, workspace_id: int) -> int:
        return len(self._subs.get(workspace_id, ()))


alert_hub = AlertHub()
