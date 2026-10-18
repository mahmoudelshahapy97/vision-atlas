# app/services/analytics_service.py
"""Windowed aggregates behind the Analytics page (ported from lost-found).

Time buckets are cut in the viewer's timezone: "busiest hour" is only useful
in the hours the operator lives in, and a UTC heatmap is off by the local
offset. generate_series supplies the empty buckets a GROUP BY would drop, so
every chart has the whole window.
"""

import csv
import io
import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

import asyncpg

from app.core.database import db_manager

logger = logging.getLogger(__name__)

# How a bucket of minutes reads, per metric kind (see camera_metric.agg).
_AGG_SQL = {
    "avg": "SUM(m.value * m.samples) / NULLIF(SUM(m.samples), 0)",
    "max": "MAX(m.value)",
    "sum": "SUM(m.value)",
}
MAX_METRIC_CAMERAS = 8


def _num(value: Any) -> Optional[float]:
    return round(float(value), 3) if value is not None else None


class AnalyticsService:
    def __init__(self) -> None:
        self.db_manager = db_manager

    async def window(self, days: int, tz: str) -> Dict[str, Any]:
        """The bucket grid, computed by Postgres so its tz database is the one
        used. One day is the last 24 hourly buckets; longer is `days` daily
        buckets ending today, aligned to bucket boundaries in `tz`."""
        bucket = "hour" if days == 1 else "day"
        step = timedelta(hours=1) if bucket == "hour" else timedelta(days=1)
        count = 24 if bucket == "hour" else days
        try:
            row = await self.db_manager.execute_query(
                """
                WITH t AS (SELECT date_trunc($1, NOW() AT TIME ZONE $2) AS end_local)
                SELECT end_local,
                       end_local - $3::interval                   AS start_local,
                       (end_local - $3::interval) AT TIME ZONE $2 AS start_at,
                       NOW()                                      AS now
                FROM t
                """,
                (bucket, tz, step * (count - 1)),
                fetch_one=True,
            )
        except asyncpg.exceptions.InvalidParameterValueError as e:
            raise ValueError(f"Unknown timezone: {tz}") from e
        return {"bucket": bucket, "step": step, "tz": tz, **row}

    @staticmethod
    def _scope(workspace_id: int, start_at, camera_id: Optional[int]) -> Tuple[str, Tuple[Any, ...]]:
        """WHERE clause and params shared by the event queries: $1 workspace, $2 window start, $3 camera."""
        where = "e.workspace_id = $1 AND e.occurred_at >= $2"
        params: Tuple[Any, ...] = (workspace_id, start_at)
        if camera_id is not None:
            where += " AND e.camera_id = $3"
            params += (camera_id,)
        return where, params

    async def summary(self, workspace_id: int, days: int, camera_id: Optional[int], tz: str) -> Dict[str, Any]:
        w = await self.window(days, tz)
        where, base = self._scope(workspace_id, w["start_at"], camera_id)
        n = len(base)

        totals = await self.db_manager.execute_query(
            f"""
            SELECT COUNT(*)                                             AS events,
                   COUNT(*) FILTER (WHERE status = 'open')              AS open,
                   COUNT(*) FILTER (WHERE severity = 'critical')        AS critical,
                   COUNT(*) FILTER (WHERE status = 'false_positive')    AS false_positives,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (handled_at - occurred_at)))
                       FILTER (WHERE handled_at IS NOT NULL)            AS median_handle_s
            FROM camera_event e WHERE {where}
            """,
            base,
            fetch_one=True,
        )
        series = await self.db_manager.execute_query(
            f"""
            WITH buckets AS (
                SELECT generate_series(${n + 1}::timestamp, ${n + 2}::timestamp, ${n + 3}::interval) AS bucket_start
            ),
            ev AS (
                SELECT date_trunc(${n + 4}, e.occurred_at AT TIME ZONE ${n + 5}) AS bucket_start, e.severity
                FROM camera_event e WHERE {where}
            )
            SELECT b.bucket_start,
                   COUNT(ev.severity)                                   AS events,
                   COUNT(*) FILTER (WHERE ev.severity = 'critical')     AS critical,
                   COUNT(*) FILTER (WHERE ev.severity = 'warning')      AS warning,
                   COUNT(*) FILTER (WHERE ev.severity = 'info')         AS info
            FROM buckets b LEFT JOIN ev ON ev.bucket_start = b.bucket_start
            GROUP BY b.bucket_start ORDER BY b.bucket_start
            """,
            base + (w["start_local"], w["end_local"], w["step"], w["bucket"], tz),
            fetch_all=True,
        )
        heatmap = await self.db_manager.execute_query(
            f"""
            SELECT EXTRACT(DOW  FROM e.occurred_at AT TIME ZONE ${n + 1})::int AS weekday,
                   EXTRACT(HOUR FROM e.occurred_at AT TIME ZONE ${n + 1})::int AS hour,
                   COUNT(*) AS events
            FROM camera_event e WHERE {where}
            GROUP BY weekday, hour ORDER BY weekday, hour
            """,
            base + (tz,),
            fetch_all=True,
        )
        by_camera = await self.db_manager.execute_query(
            f"""
            SELECT e.camera_id, c.name AS camera_name,
                   COUNT(*)                                          AS events,
                   COUNT(*) FILTER (WHERE e.status = 'open')         AS open,
                   COUNT(*) FILTER (WHERE e.severity = 'critical')   AS critical
            FROM camera_event e JOIN camera c ON c.id = e.camera_id
            WHERE {where}
            GROUP BY e.camera_id, c.name ORDER BY events DESC, camera_name
            """,
            base,
            fetch_all=True,
        )
        by_kind = await self.db_manager.execute_query(
            f"""
            SELECT e.kind, COUNT(*) AS events,
                   COUNT(*) FILTER (WHERE e.status = 'false_positive') AS false_positives,
                   AVG(e.confidence) AS avg_confidence
            FROM camera_event e WHERE {where}
            GROUP BY e.kind ORDER BY events DESC, e.kind
            """,
            base,
            fetch_all=True,
        )
        statuses = await self.db_manager.execute_query(
            f"SELECT e.status, COUNT(*) AS events FROM camera_event e WHERE {where} GROUP BY e.status",
            base,
            fetch_all=True,
        )
        events = totals["events"]
        return {
            "window": {"start": w["start_at"], "end": w["now"], "bucket": w["bucket"], "tz": tz},
            "kpis": {
                "events": events,
                "open": totals["open"],
                "critical": totals["critical"],
                "false_positives": totals["false_positives"],
                "false_positive_pct": round(100.0 * totals["false_positives"] / events, 1) if events else None,
                "median_handle_s": _num(totals["median_handle_s"]),
            },
            # naive local timestamps: wall-clock times in tz
            "series": [{**r, "bucket_start": r["bucket_start"].isoformat()} for r in series],
            "heatmap": heatmap,
            "by_camera": by_camera,
            "by_kind": [{**r, "avg_confidence": _num(r["avg_confidence"])} for r in by_kind],
            "by_status": {r["status"]: r["events"] for r in statuses},
        }

    async def metric_names(self, workspace_id: int, start_at, camera_id: Optional[int]) -> List[Dict[str, Any]]:
        return await self.db_manager.execute_query(
            """
            SELECT m.name, MIN(m.agg) AS agg, COUNT(DISTINCT m.camera_id) AS cameras
            FROM camera_metric m JOIN camera c ON c.id = m.camera_id
            WHERE c.workspace_id = $1 AND m.bucket >= $2 AND ($3::int IS NULL OR m.camera_id = $3)
            GROUP BY m.name ORDER BY COUNT(*) DESC, m.name  -- the default is the best-covered metric
            """,
            (workspace_id, start_at, camera_id),
            fetch_all=True,
        )

    async def metrics(
        self, workspace_id: int, days: int, camera_id: Optional[int], name: Optional[str], tz: str
    ) -> Dict[str, Any]:
        """One metric over the window, per camera (at most MAX_METRIC_CAMERAS
        lines), each bucket summarised the way the metric reads."""
        w = await self.window(days, tz)
        names = await self.metric_names(workspace_id, w["start_at"], camera_id)
        chosen = next((m for m in names if m["name"] == name), names[0] if names else None)
        out = {"window": {"start": w["start_at"], "end": w["now"], "bucket": w["bucket"], "tz": tz},
               "names": names, "name": None, "agg": None, "buckets": [], "series": []}
        if not chosen:
            return out
        rows = await self.db_manager.execute_query(
            f"""
            WITH buckets AS (SELECT generate_series($4::timestamp, $5::timestamp, $6::interval) AS bucket_start),
            cams AS (
                SELECT DISTINCT m.camera_id, c.name AS camera_name
                FROM camera_metric m JOIN camera c ON c.id = m.camera_id
                WHERE c.workspace_id = $1 AND m.name = $2 AND m.bucket >= $3 AND ($9::int IS NULL OR m.camera_id = $9)
                ORDER BY m.camera_id LIMIT {MAX_METRIC_CAMERAS}
            ),
            vals AS (
                SELECT m.camera_id, date_trunc($7, m.bucket AT TIME ZONE $8) AS bucket_start,
                       {_AGG_SQL[chosen['agg']]} AS value
                FROM camera_metric m
                WHERE m.camera_id IN (SELECT camera_id FROM cams) AND m.name = $2 AND m.bucket >= $3
                GROUP BY m.camera_id, 2
            )
            SELECT cams.camera_id, cams.camera_name, b.bucket_start, vals.value
            FROM cams CROSS JOIN buckets b
            LEFT JOIN vals ON vals.camera_id = cams.camera_id AND vals.bucket_start = b.bucket_start
            ORDER BY cams.camera_name, b.bucket_start
            """,
            (workspace_id, chosen["name"], w["start_at"], w["start_local"], w["end_local"], w["step"],
             w["bucket"], tz, camera_id),
            fetch_all=True,
        )
        series: Dict[int, Dict[str, Any]] = {}
        buckets: List[str] = []
        for r in rows:
            s = series.setdefault(r["camera_id"], {"camera_id": r["camera_id"], "camera_name": r["camera_name"], "values": []})
            s["values"].append(_num(r["value"]))
            if len(series) == 1:
                buckets.append(r["bucket_start"].isoformat())
        return {**out, "name": chosen["name"], "agg": chosen["agg"], "buckets": buckets, "series": list(series.values())}

    async def events_csv(self, workspace_id: int, days: int, camera_id: Optional[int], tz: str) -> str:
        w = await self.window(days, tz)
        where, base = self._scope(workspace_id, w["start_at"], camera_id)
        rows = await self.db_manager.execute_query(
            f"""
            SELECT e.id, (e.occurred_at AT TIME ZONE ${len(base) + 1}) AS occurred_local, c.name AS camera,
                   e.pipeline, e.kind, e.label, e.severity, e.track_id, e.confidence, e.status,
                   u.name AS handled_by, (e.handled_at AT TIME ZONE ${len(base) + 1}) AS handled_local
            FROM camera_event e JOIN camera c ON c.id = e.camera_id LEFT JOIN app_user u ON u.id = e.handled_by
            WHERE {where} ORDER BY e.occurred_at
            """,
            base + (tz,),
            fetch_all=True,
        )
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["id", f"occurred ({tz})", "camera", "pipeline", "kind", "label", "severity", "track",
                         "confidence", "status", "handled by", f"handled ({tz})"])
        for r in rows:
            writer.writerow([r["id"], r["occurred_local"].isoformat(sep=" ", timespec="seconds"), r["camera"], r["pipeline"],
                             r["kind"], r["label"], r["severity"], r["track_id"], r["confidence"], r["status"],
                             r["handled_by"] or "", r["handled_local"].isoformat(sep=" ", timespec="seconds") if r["handled_local"] else ""])
        return buf.getvalue()


analytics_service = AnalyticsService()
