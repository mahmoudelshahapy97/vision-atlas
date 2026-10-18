# tests/test_workspaces.py
"""Workspaces, membership roles, and models shared with a workspace."""

import uuid

from app.vision.registry import manager


def _user(client, admin_headers, name="Member"):
    email = f"{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/users", headers=admin_headers, json={"email": email, "name": name, "password": "pass-word-123"})
    assert r.status_code == 201, r.text
    login = client.post("/api/auth/login", json={"email": email, "password": "pass-word-123"}).json()
    return {"id": r.json()["id"], "email": email, "headers": {"Authorization": f"Bearer {login['access_token']}"}}


def _workspace(client, admin_headers, **body):
    r = client.post("/api/workspaces", headers=admin_headers, json={"name": f"WS {uuid.uuid4().hex[:6]}", **body})
    assert r.status_code == 201, r.text
    return r.json()


def test_only_system_admins_create_workspaces(client, admin_headers, user_headers):
    body = {"name": f"Plant {uuid.uuid4().hex[:6]}"}
    assert client.post("/api/workspaces", headers=user_headers, json=body).status_code == 403
    r = client.post("/api/workspaces", headers=admin_headers, json={**body, "enabled_pipelines": ["restricted_zone", "detect"]})
    assert r.status_code == 201
    ws = r.json()
    assert ws["slug"].startswith("plant-") and ws["enabled_pipelines"] == ["detect", "restricted_zone"]
    assert client.post("/api/workspaces", headers=admin_headers, json=body).status_code == 409
    bad = client.post("/api/workspaces", headers=admin_headers, json={"name": "X" + body["name"], "enabled_pipelines": ["nope"]})
    assert bad.status_code == 422
    # PATCH: null means every pipeline again
    r = client.patch(f"/api/workspaces/{ws['id']}", headers=admin_headers, json={"enabled_pipelines": None, "max_cameras": 4})
    assert r.status_code == 200 and r.json()["enabled_pipelines"] is None and r.json()["max_cameras"] == 4


def test_membership_and_roles(client, admin_headers):
    ws = _workspace(client, admin_headers)
    a, b, outsider = (_user(client, admin_headers, n) for n in ("Alice", "Bob", "Eve"))
    wid = ws["id"]

    assert client.get(f"/api/workspaces/{wid}", headers=outsider["headers"]).status_code == 404
    assert client.post(f"/api/workspaces/{wid}/members", headers=admin_headers,
                       json={"email": "nobody-here@example.com"}).status_code == 404
    r = client.post(f"/api/workspaces/{wid}/members", headers=admin_headers, json={"email": a["email"], "role": "viewer"})
    assert r.status_code == 201 and r.json()["role"] == "viewer"
    assert client.post(f"/api/workspaces/{wid}/members", headers=admin_headers, json={"email": a["email"]}).status_code == 409

    mine = client.get("/api/workspaces/mine", headers=a["headers"]).json()
    assert [(w["id"], w["my_role"]) for w in mine] == [(wid, "viewer")]
    assert client.get(f"/api/workspaces/{wid}/members", headers=a["headers"]).status_code == 200
    # a viewer can't add people
    assert client.post(f"/api/workspaces/{wid}/members", headers=a["headers"], json={"email": b["email"]}).status_code == 403

    # a workspace admin manages members ...
    client.patch(f"/api/workspaces/{wid}/members/{a['id']}", headers=admin_headers, json={"role": "admin"})
    assert client.post(f"/api/workspaces/{wid}/members", headers=a["headers"],
                       json={"email": b["email"], "role": "operator"}).status_code == 201
    # ... but can't leave the workspace without an admin
    assert client.patch(f"/api/workspaces/{wid}/members/{a['id']}", headers=a["headers"], json={"role": "viewer"}).status_code == 409
    assert client.delete(f"/api/workspaces/{wid}/members/{a['id']}", headers=a["headers"]).status_code == 409
    assert client.patch(f"/api/workspaces/{wid}/members/{b['id']}", headers=a["headers"], json={"role": "admin"}).status_code == 200
    assert client.patch(f"/api/workspaces/{wid}/members/{a['id']}", headers=a["headers"], json={"role": "viewer"}).status_code == 200

    # anyone may leave; only admins remove others; workspace settings stay with system admins
    assert client.delete(f"/api/workspaces/{wid}/members/{b['id']}", headers=a["headers"]).status_code == 403
    assert client.patch(f"/api/workspaces/{wid}", headers=b["headers"], json={"name": "Mine now"}).status_code == 403
    assert client.delete(f"/api/workspaces/{wid}/members/{a['id']}", headers=a["headers"]).status_code == 204
    assert client.get(f"/api/workspaces/{wid}", headers=a["headers"]).status_code == 404


def test_a_deactivated_workspace_locks_members_out(client, admin_headers):
    ws = _workspace(client, admin_headers)
    m = _user(client, admin_headers)
    client.post(f"/api/workspaces/{ws['id']}/members", headers=admin_headers, json={"email": m["email"], "role": "admin"})
    assert client.patch(f"/api/workspaces/{ws['id']}", headers=admin_headers, json={"is_active": False}).status_code == 200
    assert client.get(f"/api/workspaces/{ws['id']}", headers=m["headers"]).status_code == 403
    assert client.get("/api/workspaces/mine", headers=m["headers"]).json() == []
    assert client.get(f"/api/workspaces/{ws['id']}", headers=admin_headers).status_code == 200
    assert any(w["id"] == ws["id"] for w in client.get("/api/workspaces", headers=admin_headers).json())


def test_models_shared_with_a_workspace(client, admin_headers, tmp_path):
    ws = _workspace(client, admin_headers)
    owner, member, outsider = (_user(client, admin_headers, n) for n in ("Owner", "Viewer", "Outsider"))
    client.post(f"/api/workspaces/{ws['id']}/members", headers=admin_headers, json={"email": owner["email"], "role": "operator"})
    client.post(f"/api/workspaces/{ws['id']}/members", headers=admin_headers, json={"email": member["email"], "role": "viewer"})

    src = manager.fetch_file("yolo26-detect", tmp_path / "served")

    def upload(who, **data):
        with open(src, "rb") as f:
            return client.post("/api/models/upload", headers=who["headers"], data={"name": "Team detector", **data},
                               files={"file": ("best.pt", f)})

    assert upload(member, workspace_id=str(ws["id"])).status_code == 403   # viewers can't share into it
    assert upload(outsider, workspace_id=str(ws["id"])).status_code == 404
    r = upload(owner, workspace_id=str(ws["id"]))
    assert r.status_code == 201, r.text
    model = r.json()
    assert model["workspace_id"] == ws["id"] and model["workspace_name"] == ws["name"]
    key = f"custom:{model['id']}"

    def visible(who):
        return any(m["id"] == model["id"] for m in client.get("/api/models", headers=who["headers"]).json()["custom"])

    assert visible(member) and not visible(outsider)
    lab = client.get("/api/projects/1/lab", headers=member["headers"]).json()
    assert any(c["key"] == key and c["workspace"] == ws["name"] for c in lab["tabs"][0]["custom_models"])
    run = client.post("/api/runs", headers=outsider["headers"],
                      data={"project_id": "1", "samples": '{"media": ["bus.jpg"]}', "params": f'{{"model": "{key}"}}'})
    assert run.status_code == 404
    assert client.delete(f"/api/models/custom/{model['id']}", headers=member["headers"]).status_code == 403

    # Deleting the workspace hands the model back to its owner only.
    assert client.delete(f"/api/workspaces/{ws['id']}", headers=admin_headers).status_code == 204
    assert visible(owner) and not visible(member)
    assert client.delete(f"/api/models/custom/{model['id']}", headers=owner["headers"]).status_code == 204
