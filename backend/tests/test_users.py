# tests/test_users.py
"""Refresh tokens, revocation and admin account management."""

import uuid


def _register(client, name="Someone", password="pass-word-123"):
    email = f"{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/auth/register", json={"email": email, "name": name, "password": password})
    assert r.status_code == 201, r.text
    body = r.json()
    return email, body, {"Authorization": f"Bearer {body['access_token']}"}


# ------------------------------------------------------------------ sessions

def test_refresh_rotates_and_a_replayed_token_ends_every_session(client):
    _, body, _ = _register(client)
    first = body["refresh_token"]

    r = client.post("/api/auth/refresh", json={"refresh_token": first})
    assert r.status_code == 200, r.text
    second = r.json()
    assert second["refresh_token"] != first
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {second['access_token']}"}).status_code == 200

    # Replaying the used token fails and revokes the newer session as well.
    assert client.post("/api/auth/refresh", json={"refresh_token": first}).status_code == 401
    assert client.post("/api/auth/refresh", json={"refresh_token": second["refresh_token"]}).status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {second['access_token']}"}).status_code == 401


def test_an_access_token_is_not_a_refresh_token(client):
    _, body, _ = _register(client)
    assert client.post("/api/auth/refresh", json={"refresh_token": body["access_token"]}).status_code == 401


def test_logout_ends_only_that_session(client):
    email, body, headers = _register(client)
    other = client.post("/api/auth/login", json={"email": email, "password": "pass-word-123"}).json()
    assert client.post("/api/auth/logout", json={"refresh_token": body["refresh_token"]}).status_code == 204
    assert client.post("/api/auth/refresh", json={"refresh_token": body["refresh_token"]}).status_code == 401
    assert client.post("/api/auth/refresh", json={"refresh_token": other["refresh_token"]}).status_code == 200


def test_logout_all_revokes_access_tokens_too(client):
    _, body, headers = _register(client)
    assert client.post("/api/auth/logout-all", headers=headers).status_code == 204
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    assert client.post("/api/auth/refresh", json={"refresh_token": body["refresh_token"]}).status_code == 401


def test_change_password(client):
    email, body, headers = _register(client)
    bad = client.post("/api/auth/change-password", headers=headers,
                      json={"current_password": "wrong-one-1", "new_password": "new-pass-word-1"})
    assert bad.status_code == 400
    r = client.post("/api/auth/change-password", headers=headers,
                    json={"current_password": "pass-word-123", "new_password": "new-pass-word-1"})
    assert r.status_code == 200, r.text
    assert client.get("/api/auth/me", headers=headers).status_code == 401  # old token revoked
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).status_code == 200
    assert client.post("/api/auth/refresh", json={"refresh_token": body["refresh_token"]}).status_code == 401
    assert client.post("/api/auth/login", json={"email": email, "password": "new-pass-word-1"}).status_code == 200


# ------------------------------------------------------------------ admin

def test_users_routes_need_an_admin(client, user_headers):
    assert client.get("/api/users").status_code == 401
    assert client.get("/api/users", headers=user_headers).status_code == 403


def test_admin_creates_lists_updates_and_deletes_a_user(client, admin_headers):
    email = f"{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/users", headers=admin_headers,
                    json={"email": email, "name": "Made By Admin", "password": "pass-word-123"})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    assert r.json()["role"] == "user" and r.json()["is_active"]
    assert client.post("/api/users", headers=admin_headers,
                       json={"email": email, "name": "Dup", "password": "pass-word-123"}).status_code == 409

    page = client.get("/api/users", headers=admin_headers, params={"q": email[:8]}).json()
    assert page["total"] == 1 and page["items"][0]["id"] == uid

    login = client.post("/api/auth/login", json={"email": email, "password": "pass-word-123"}).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}

    # Promotion takes effect at once: the old token (old token_version) stops working.
    r = client.patch(f"/api/users/{uid}", headers=admin_headers, json={"role": "admin", "name": "Promoted"})
    assert r.status_code == 200 and r.json()["role"] == "admin" and r.json()["name"] == "Promoted"
    assert client.get("/api/auth/me", headers=headers).status_code == 401

    # Deactivated: can't sign in, can't refresh.
    assert client.patch(f"/api/users/{uid}", headers=admin_headers, json={"is_active": False}).status_code == 200
    assert client.post("/api/auth/login", json={"email": email, "password": "pass-word-123"}).status_code == 401
    assert client.post("/api/auth/refresh", json={"refresh_token": login["refresh_token"]}).status_code == 401

    assert client.delete(f"/api/users/{uid}", headers=admin_headers).status_code == 204
    assert client.get(f"/api/users/{uid}", headers=admin_headers).status_code == 404


def test_reset_password_signs_the_user_out(client, admin_headers):
    email, body, headers = _register(client)
    uid = client.get("/api/auth/me", headers=headers).json()["id"]
    r = client.post(f"/api/users/{uid}/reset-password", headers=admin_headers, json={"new_password": "reset-pass-99"})
    assert r.status_code == 204
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    assert client.post("/api/auth/login", json={"email": email, "password": "reset-pass-99"}).status_code == 200


def test_an_admin_cannot_remove_themself_or_the_last_admin(client, admin_headers):
    me = client.get("/api/auth/me", headers=admin_headers).json()
    assert client.delete(f"/api/users/{me['id']}", headers=admin_headers).status_code == 400
    assert client.patch(f"/api/users/{me['id']}", headers=admin_headers, json={"role": "user"}).status_code == 400
    assert client.patch(f"/api/users/{me['id']}", headers=admin_headers, json={"is_active": False}).status_code == 400
    # Renaming yourself is fine.
    r = client.patch(f"/api/users/{me['id']}", headers=admin_headers, json={"name": me["name"]})
    assert r.status_code == 200
