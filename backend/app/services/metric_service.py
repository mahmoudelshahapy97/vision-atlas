# app/services/metric_service.py
"""Per-minute camera metrics: workers sample their analyzer's metrics every
frame (MinuteAccumulator) and write each finished minute here; the analytics
charts read them back (analytics_service)."""

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from app.core.database import db_manager

logger = logging.getLogger(__name__)

# (bucket, name, agg, value, samples)
MetricRow = Tuple[datetime, str, str, float, int]


def agg_of(declared: Dict[str, str], name: str) -> str:
    """How a metric is summarised, from the analyzer's declaration; a
    "count:<class>" metric matches "count:<class>"."""
    if name in declared:
        return declared[name]
    prefix = name.split(":", 1)[0]
    return declared.get(f"{prefix}:<class>", "avg")


class MinuteAccumulator:
    """Folds one camera's per-frame metrics into minutes."""

    def __init__(self, declared: Dict[str, str]):
        self.declared = declared
        self.minute: Optional[datetime] = None
        self._sum: Dict[str, float] = defaultdict(float)
        self._max: Dict[str, float] = {}
        self._n: Dict[str, int] = defaultdict(int)

    def add(self, metrics: Dict[str, float], at: datetime) -> List[MetricRow]:
        """Returns the previous minute's rows once a new minute starts."""
        minute = at.astimezone(timezone.utc).replace(second=0, microsecond=0)
        done = self.flush() if self.minute is not None and minute != self.minute else []
        self.minute = minute
        for name, value in metrics.items():
            v = float(value)
            self._sum[name] += v
            self._max[name] = max(self._max.get(name, v), v)
            self._n[name] += 1
        return done

    def flush(self) -> List[MetricRow]:
        rows = []
        for name, n in self._n.items():
            agg = agg_of(self.declared, name)
            value = self._sum[name] if agg == "sum" else self._max[name] if agg == "max" else self._sum[name] / n
            rows.append((self.minute, name, agg, round(value, 4), n))
        self._sum.clear()
        self._max.clear()
        self._n.clear()
        return rows


class MetricService:
    def __init__(self) -> None:
        self.db_manager = db_manager

    async def write(self, camera_id: int, rows: List[MetricRow]) -> None:
        """Upsert: a minute written twice (a worker restarted within it) is merged."""
        if not rows:
            return
        await self.db_manager.execute_many(
            """
            INSERT INTO camera_metric (camera_id, bucket, name, agg, value, samples)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (camera_id, bucket, name) DO UPDATE SET
                value = CASE camera_metric.agg
                    WHEN 'sum' THEN camera_metric.value + EXCLUDED.value
                    WHEN 'max' THEN GREATEST(camera_metric.value, EXCLUDED.value)
                    ELSE (camera_metric.value * camera_metric.samples + EXCLUDED.value * EXCLUDED.samples)
                         / (camera_metric.samples + EXCLUDED.samples)
                END,
                samples = camera_metric.samples + EXCLUDED.samples
            """,
            [(camera_id, *row) for row in rows],
        )

    async def purge(self, older_than_days: int) -> int:
        return await self.db_manager.execute_query(
            "DELETE FROM camera_metric WHERE bucket < NOW() - make_interval(days => $1)",
            (older_than_days,),
            return_rowcount=True,
        )


metric_service = MetricService()
