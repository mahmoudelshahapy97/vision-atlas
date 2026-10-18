# tests/test_analytics.py
"""Per-minute metrics and the analytics queries: bucket filling, the viewer's
timezone, metric summaries, workspace isolation and the CSV export."""

import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.database import db_manager
from app.services.metric_service import MinuteAccumulator, agg_of

UTC = timezone.utc


# ------------------------------------------------------------------ accumulator (no database)

def test_metrics_fold_into_minutes_the_way_they_read():
    acc = MinuteAccumulator({"in_zone": "max", "in": "sum", "count:<class>": "avg"})
    t = datetime(2026, 10, 18, 9, 30, 5, tzinfo=UTC)
    assert acc.add({"in_zone": 1, "in": 2, "count:person": 4}, t) == []
    assert acc.add({"in_zone": 3, "in": 1, "count:person": 2}, t + timedelta(seconds=20)) == []
    rows = acc.add({"in_zone": 0, "in": 0}, t + timedelta(minutes=1))
    got = {name: (agg, value, n) for bucket, name, agg, value, n in rows}
    assert {b for b, *_ in rows} == {t.replace(second=0)}
    assert got == {"in_zone": ("max", 3.0, 2), "in": ("sum", 3.0, 2), "count:person": ("avg", 3.0, 2)}
    assert agg_of({}, "anything") == "avg"


# ------------------------------------------------------------------ queries on seeded data

@pytest.fixture(scope="module")
def seeded(client, admin_headers):
    """Two workspaces; the first has two cameras with events and metrics at known times."""
    def ws(name):
        return client.post("/api/workspaces", headers=admin_headers, json={"name": f"{name} {uuid.uuid4().hex[:6]}"}).json()

    a, b = ws("Analytics"), ws("Elsewhere")
    ha = {**admin_headers, "X-Workspace-Id": str(a["id"])}
    hb = {**admin_headers, "X-Workspace-Id": str(b["id"])}
    gate = client.post("/api/cameras", headers=ha, json={"name": "Gate", "source_url": "sample:street.mp4"}).json()
    dock = client.post("/api/cameras", headers=ha, json={"name": "Dock", "source_url": "sample:fall.mp4"}).json()
    client.post("/api/cameras", headers=hb, json={"name": "Other", "source_url": "sample:fall.mp4"})

    now = datetime.now(UTC).replace(second=0, microsecond=0)
    hour_ago = now.replace(minute=10) - timedelta(hours=1)  # +1 minute stays in the same hourly bucket
    events = [  # (camera, kind, severity, status, when)
        (gate, "zone_entry", "warning", "open", now - timedelta(minutes=5)),
        (gate, "zone_entry", "warning", "resolved", now - timedelta(minutes=50)),
        (gate, "zone_entry", "warning", "false_positive", now - timedelta(hours=3)),
        (dock, "fall", "critical", "open", now - timedelta(minutes=10)),
        (dock, "fall", "critical", "acknowledged", now - timedelta(days=3)),
        (dock, "fall", "critical", "open", now - timedelta(days=20)),
    ]
    metrics = [  # (camera, minute, name, agg, value, samples)
        (gate, hour_ago, "in_zone", "max", 2, 10),
        (gate, hour_ago + timedelta(minutes=1), "in_zone", "max", 5, 10),
        (gate, now, "in_zone", "max", 1, 10),
        (dock, hour_ago, "in_zone", "max", 7, 10),
        (gate, hour_ago, "people", "avg", 1.0, 30),
        (gate, hour_ago + timedelta(minutes=1), "people", "avg", 4.0, 10),
        (gate, hour_ago, "in", "sum", 3, 30),
        (gate, hour_ago + timedelta(minutes=1), "in", "sum", 4, 30),
    ]

    async def seed():
        for cam, kind, sev, status, at in events:
            await db_manager.execute_query(
                """
                INSERT INTO camera_event (workspace_id, camera_id, pipeline, kind, label, severity, status, occurred_at,
                                          handled_at, confidence)
                VALUES ($1, $2, 'restricted_zone', $3, 'person', $4, $5, $6,
                        CASE WHEN $5::text = 'open' THEN NULL ELSE $6::timestamptz + INTERVAL '2 minutes' END, 0.8)
                """,
                (a["id"], cam["id"], kind, sev, status, at),
            )
        for cam, minute, name, agg, value, samples in metrics:
            await db_manager.execute_query(
                "INSERT INTO camera_metric (camera_id, bucket, name, agg, value, samples) VALUES ($1, $2, $3, $4, $5, $6)",
                (cam["id"], minute, name, agg, value, samples),
            )

    client.portal.call(seed)
    return {"a": ha, "b": hb, "gate": gate, "dock": dock}


def test_summary_counts_and_fills_every_bucket(client, seeded):
    day = client.get("/api/analytics/summary", headers=seeded["a"], params={"days": 1, "tz": "UTC"}).json()
    assert day["window"]["bucket"] == "hour" and len(day["series"]) == 24
    assert sum(b["events"] for b in day["series"]) == 4  # the 3-day and 20-day ones fall outside
    k = day["kpis"]
    assert (k["events"], k["open"], k["critical"], k["false_positives"]) == (4, 2, 1, 1)
    assert k["median_handle_s"] == 120.0
    assert {r["camera_name"]: r["events"] for r in day["by_camera"]} == {"Gate": 3, "Dock": 1}
    assert {r["kind"]: r["events"] for r in day["by_kind"]} == {"zone_entry": 3, "fall": 1}
    assert day["by_status"] == {"open": 2, "resolved": 1, "false_positive": 1}

    month = client.get("/api/analytics/summary", headers=seeded["a"], params={"days": 30}).json()
    assert month["window"]["bucket"] == "day" and len(month["series"]) == 30 and month["kpis"]["events"] == 6
    assert sum(c["events"] for c in month["heatmap"]) == 6
    one = client.get("/api/analytics/summary", headers=seeded["a"], params={"days": 30, "camera_id": seeded["dock"]["id"]}).json()
    assert one["kpis"]["events"] == 3


def test_buckets_and_heatmap_follow_the_viewers_timezone(client, seeded):
    utc = client.get("/api/analytics/summary", headers=seeded["a"], params={"days": 1, "tz": "UTC"}).json()
    riyadh = client.get("/api/analytics/summary", headers=seeded["a"], params={"days": 1, "tz": "Asia/Riyadh"}).json()
    # the same events, three hours later on the clock
    assert sorted(c["hour"] for c in riyadh["heatmap"]) == sorted((c["hour"] + 3) % 24 for c in utc["heatmap"])
    assert utc["series"][-1]["bucket_start"][11:13] != riyadh["series"][-1]["bucket_start"][11:13]
    r = client.get("/api/analytics/summary", headers=seeded["a"], params={"tz": "Mars/Olympus"})
    assert r.status_code == 422
    assert client.get("/api/analytics/summary", headers=seeded["a"], params={"days": 5}).status_code == 422


def test_metric_series_per_camera(client, seeded):
    r = client.get("/api/analytics/metrics", headers=seeded["a"], params={"days": 1, "name": "in_zone"}).json()
    assert r["name"] == "in_zone" and r["agg"] == "max" and len(r["buckets"]) == 24
    lines = {s["camera_name"]: s["values"] for s in r["series"]}
    assert set(lines) == {"Gate", "Dock"}
    assert max(v for v in lines["Gate"] if v is not None) == 5 and max(v for v in lines["Dock"] if v is not None) == 7
    names = {m["name"]: m["agg"] for m in r["names"]}
    assert names == {"in_zone": "max", "people": "avg", "in": "sum"}

    def peak(name):
        s = client.get("/api/analytics/metrics", headers=seeded["a"], params={"days": 1, "name": name}).json()["series"][0]
        return [v for v in s["values"] if v is not None]

    assert peak("people") == [pytest.approx(1.75)]   # (1*30 + 4*10) / 40, weighted by samples
    assert peak("in") == [7]                         # a total
    empty = client.get("/api/analytics/metrics", headers=seeded["b"], params={"days": 1}).json()
    assert empty["name"] is None and empty["series"] == []


def test_analytics_stay_in_their_workspace(client, seeded, user_headers):
    other = client.get("/api/analytics/summary", headers=seeded["b"], params={"days": 30}).json()
    assert other["kpis"]["events"] == 0 and other["by_camera"] == []
    # a camera id from the other workspace doesn't leak its numbers
    leak = client.get("/api/analytics/summary", headers=seeded["b"], params={"days": 30, "camera_id": seeded["gate"]["id"]}).json()
    assert leak["kpis"]["events"] == 0
    outsider = {**user_headers, "X-Workspace-Id": seeded["a"]["X-Workspace-Id"]}
    assert client.get("/api/analytics/summary", headers=outsider).status_code == 404


def test_events_csv(client, seeded):
    r = client.get("/api/analytics/events.csv", headers=seeded["a"], params={"days": 7, "tz": "Asia/Riyadh"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("id,occurred (Asia/Riyadh),camera") and len(lines) == 1 + 5


def test_a_running_camera_writes_its_metrics(client, admin_headers):
    ws = client.post("/api/workspaces", headers=admin_headers, json={"name": f"Metrics {uuid.uuid4().hex[:6]}"}).json()
    h = {**admin_headers, "X-Workspace-Id": str(ws["id"])}
    cam = client.post("/api/cameras", headers=h, json={"name": "Hall", "source_url": "sample:fall.mp4", "pipeline": "detect",
                                                       "params": {"classes": ["person"]}, "target_fps": 5}).json()
    client.post(f"/api/cameras/{cam['id']}/start", headers=h)
    t0 = time.time()
    while time.time() - t0 < 60 and client.get(f"/api/cameras/{cam['id']}", headers=h).json()["status"].get("frames_processed", 0) < 3:
        time.sleep(0.3)
    client.post(f"/api/cameras/{cam['id']}/stop", headers=h)  # writes the minute in progress
    rows = client.portal.call(lambda: db_manager.execute_query(
        "SELECT name, agg, samples FROM camera_metric WHERE camera_id = $1", (cam["id"],), fetch_all=True))
    got = {r["name"]: r["agg"] for r in rows}
    assert got.get("objects") == "avg" and got.get("count:person") == "avg"
    assert all(r["samples"] >= 1 for r in rows)
