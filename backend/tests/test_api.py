def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_catalog_seeded(client):
    page = client.get("/api/projects").json()
    assert page["total"] == 90
    assert [p["id"] for p in page["items"]][:3] == [1, 2, 3]
    assert len(client.get("/api/domains").json()) == 15
    tasks = client.get("/api/task-types").json()
    assert len(tasks) == 10 and all(len(t["steps"]) == 5 for t in tasks)
    assert sum(t["project_count"] for t in tasks) == 90
    techs = client.get("/api/technologies?limit=5").json()
    assert techs[0]["name"] == "YOLO"


def test_filters_and_search(client):
    assert client.get("/api/projects", params={"domain": "D"}).json()["total"] == 5
    assert client.get("/api/projects", params={"picks": True}).json()["total"] == 13
    arabic = client.get("/api/projects", params={"q": "arabic"}).json()
    assert {p["id"] for p in arabic["items"]} >= {2, 11, 12, 15}
    combo = client.get("/api/projects", params={"q": "yolo", "level": 1}).json()
    assert combo["total"] > 0 and all(p["level"] == 1 for p in combo["items"])
    assert client.get("/api/projects", params={"q": "100%_"}).json()["total"] == 0
    paged = client.get("/api/projects", params={"size": 10, "page": 9}).json()
    assert [p["id"] for p in paged["items"]] == list(range(81, 91))


def test_facets_ignore_own_dimension(client):
    f = client.get("/api/projects/facets", params={"domain": "D"}).json()
    assert f["total"] == 5
    assert sum(d["count"] for d in f["domains"]) == 90  # domain counts ignore the domain filter
    assert sum(t["count"] for t in f["task_types"]) == 5


def test_detail_by_id_and_slug(client):
    p = client.get("/api/projects/2").json()
    assert p["title"].startswith("Automatic License Plate")
    assert p["is_pick"] and p["steps"] and p["prev_id"] == 1 and p["next_id"] == 3
    assert client.get(f"/api/projects/{p['slug']}").json()["id"] == 2
    assert client.get("/api/projects/9999").status_code == 404


def test_auth_errors(client):
    assert client.post("/api/auth/login", json={"email": "nobody@x.io", "password": "whatever1"}).status_code == 401
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/register", json={"email": "bad", "name": "x", "password": "12345678"}).status_code == 422
    assert client.get("/api/projects", params={"status": "active"}).status_code == 401


def test_progress_flow(client, user_headers):
    h = user_headers
    assert client.put("/api/projects/2/progress", json={"status": "building"}, headers=h).json()["status"] == "building"
    client.put("/api/projects/41/progress", json={"status": "done", "notes": "mAP 0.81"}, headers=h)
    client.put("/api/projects/60/progress", json={"notes": "Try BlenderProc"}, headers=h)

    item = client.get("/api/projects/2", headers=h).json()
    assert item["progress"]["status"] == "building"
    active = client.get("/api/projects", params={"status": "active"}, headers=h).json()
    assert {p["id"] for p in active["items"]} == {2, 41}

    stats = client.get("/api/me/stats", headers=h).json()
    assert stats["counts"] == {"idea": 88, "planned": 0, "building": 1, "done": 1}
    f = next(d for d in stats["by_domain"] if d["code"] == "F")
    assert f["done"] == 1 and f["total"] == 9

    mine = client.get("/api/me/progress", headers=h).json()
    assert {p["id"] for p in mine} == {2, 41, 60}

    # back to idea with no notes removes the record
    client.put("/api/projects/60/progress", json={"notes": ""}, headers=h)
    assert {p["id"] for p in client.get("/api/me/progress", headers=h).json()} == {2, 41}
    assert client.delete("/api/projects/2/progress", headers=h).status_code == 204
    assert client.put("/api/projects/999/progress", json={"status": "done"}, headers=h).status_code == 404
    assert client.put("/api/projects/1/progress", json={"status": "nope"}, headers=h).status_code == 422


def test_admin_crud(client, admin_headers, user_headers):
    body = {"title": "Drone Crowd Density Estimation", "description": "Estimate crowd density from drone footage.",
            "domain_code": "E", "task_type_code": "det", "level": 3, "technologies": ["YOLO", "CSRNet", "yolo"]}
    assert client.post("/api/projects", json=body, headers=user_headers).status_code == 403
    r = client.post("/api/projects", json=body, headers=admin_headers)
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["id"] == 91 and p["technologies"] == ["YOLO", "CSRNet"] and p["slug"] == "drone-crowd-density-estimation"

    r = client.patch(f"/api/projects/{p['id']}", json={"level": 2, "technologies": ["CSRNet"], "is_pick": True,
                                                        "pick_reason": "New idea"}, headers=admin_headers)
    assert r.status_code == 200, r.text
    u = r.json()
    assert u["level"] == 2 and u["technologies"] == ["CSRNet"] and u["is_pick"]
    assert client.patch(f"/api/projects/{p['id']}", json={"domain_code": "ZZ"}, headers=admin_headers).status_code == 422

    assert client.delete(f"/api/projects/{p['id']}", headers=admin_headers).status_code == 204
    assert client.get(f"/api/projects/{p['id']}").status_code == 404
    assert client.get("/api/projects").json()["total"] == 90
