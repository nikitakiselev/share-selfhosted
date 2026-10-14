from __future__ import annotations

from dataclasses import replace

from starlette.testclient import TestClient

from share_app import accounts
from share_app.quota import GiB
from tests.conftest import (
    BASE_URL,
    EXTERNAL_IP,
    INTERNAL_IP,
    USER_PASSWORD,
    new_share,
    tus_create,
    upload,
)

DAY = 86400


def _user(admin: TestClient, login: str) -> dict:
    return next(u for u in admin.get("/api/admin/users").json()["users"] if u["login"] == login)


def test_list_users(admin: TestClient, user: TestClient, make_user):
    upload(user, new_share(user)["slug"], b"x" * 100)
    tus_create(user, new_share(user)["slug"], 50)
    make_user("bob", quota=50 * GiB)
    make_user("unl", quota=None)
    body = admin.get("/api/admin/users").json()
    users = {u["login"]: u for u in body["users"]}
    assert list(users) == ["admin", "alice", "bob", "unl"]
    owner = users["admin"]
    assert owner["email"] == "admin@example.com"
    assert owner["role"] == "admin" and owner["quota"] is None
    alice = users["alice"]
    assert alice == {
        "id": user.user_id, "login": "alice", "email": "alice@example.com", "role": "user", "quota": GiB,
        "used": 150, "share_count": 2, "created_at": alice["created_at"], "last_login_at": None, "blocked": False,
    }
    assert users["bob"]["quota"] == 50 * GiB and users["unl"]["quota"] is None
    # unlimited is not part of the sum
    assert body["allocated"] == GiB + 50 * GiB
    assert set(body["disk"]) == {"used", "total", "free"}
    assert body["default_quota"] == GiB


def test_default_quota_unlimited(app, admin: TestClient, monkeypatch):
    monkeypatch.setattr(app.state.ctx, "settings", replace(app.state.ctx.settings, default_quota=None))
    assert admin.get("/api/admin/users").json()["default_quota"] is None
    inv = admin.post("/api/admin/invites", json={"email": "u@example.com"}).json()
    assert inv["quota"] is None


def test_set_quota(admin: TestClient, user: TestClient, ctx):
    url = f"/api/admin/users/{user.user_id}"
    u = admin.patch(url, json={"quota": 10 * GiB}).json()
    assert u["quota"] == 10 * GiB and ctx.db.get_user(user.user_id)["quota_bytes"] == 10 * GiB
    # the user sees the new quota right away
    assert user.get("/api/auth/session").json()["user"]["quota"] == 10 * GiB
    assert admin.patch(url, json={"quota": None}).json()["quota"] is None
    assert user.get("/api/app/usage").json()["quota"] is None
    # below the used space is fine: files stay, new ones cannot be uploaded
    upload(user, new_share(user)["slug"], b"x" * 100)
    assert admin.patch(url, json={"quota": 10}).json()["quota"] == 10
    assert user.get("/api/app/usage").json()["free"] == 0
    # an admin can have a quota too
    me = admin.patch(f"/api/admin/users/{admin.user_id}", json={"quota": 5 * GiB}).json()
    assert me["quota"] == 5 * GiB
    assert admin.patch(f"/api/admin/users/{admin.user_id}", json={"quota": None}).json()["quota"] is None


def test_set_quota_validation(admin: TestClient, user: TestClient):
    url = f"/api/admin/users/{user.user_id}"
    for bad in (0, -1, 1.5, "10", True, "unlimited"):
        r = admin.patch(url, json={"quota": bad})
        assert r.status_code == 400 and r.json()["error"] == "bad_quota", bad
    assert admin.patch(url, json={"quota": 0}).json()["error"] == "bad_quota"
    # an error in one field does not apply the others
    assert admin.patch(url, json={"blocked": True, "quota": 0}).status_code == 400
    assert user.get("/api/app/shares").status_code == 200
    assert _user(admin, "alice")["quota"] == GiB
    assert admin.patch(url, json={"blocked": "yes"}).json()["error"] == "bad_request"
    assert admin.patch("/api/admin/users/9999", json={"quota": GiB}).status_code == 404


def test_block_and_unblock(admin: TestClient, user: TestClient, make_client, outsider: TestClient):
    slug = new_share(user)["slug"]
    upload(user, slug, b"hello", "a.txt")
    assert outsider.get(f"/api/public/shares/{slug}").status_code == 200
    url = f"/api/admin/users/{user.user_id}"
    assert admin.patch(url, json={"blocked": True}).json()["blocked"] is True

    # the live session is gone, sign-in is 403 blocked
    assert user.get("/api/app/shares").status_code == 401
    r = make_client(EXTERNAL_IP).post("/api/auth/login", json={"email": "alice@example.com", "password": USER_PASSWORD})
    assert r.status_code == 403 and r.json()["error"] == "blocked"
    # public links look missing
    assert outsider.get(f"/api/public/shares/{slug}").json()["error"] == "not_found"
    assert _user(admin, "alice")["blocked"] is True
    assert "Link unavailable" in outsider.get(f"/s/{slug}").text
    assert "a.txt" not in outsider.get(f"/s/{slug}").text

    assert admin.patch(url, json={"blocked": False}).json()["blocked"] is False
    assert outsider.get(f"/api/public/shares/{slug}").status_code == 200
    c = make_client(EXTERNAL_IP)
    assert c.post("/api/auth/login", json={"email": "alice@example.com", "password": USER_PASSWORD}).status_code == 204


def test_admin_cannot_be_blocked_or_deleted(admin: TestClient):
    url = f"/api/admin/users/{admin.user_id}"
    r = admin.patch(url, json={"blocked": True})
    assert r.status_code == 400 and r.json()["error"] == "bad_request"
    r = admin.delete(url)
    assert r.status_code == 400 and r.json()["error"] == "bad_request"
    assert admin.get("/api/app/shares").status_code == 200


def test_delete_user(admin: TestClient, user: TestClient, ctx):
    slug = new_share(user)["slug"]
    fid = upload(user, slug, b"hello")
    pending = tus_create(user, slug, 100).headers["location"].rsplit("/", 1)[1]
    assert admin.delete(f"/api/admin/users/{user.user_id}").status_code == 204
    assert ctx.db.get_user(user.user_id) is None and ctx.db.get_share(slug) is None
    assert not ctx.storage.file_path(fid).exists() and not ctx.storage.upload_path(pending).exists()
    assert ctx.db.user_sessions(user.user_id) == []
    assert user.get("/api/app/shares").status_code == 401
    assert admin.delete(f"/api/admin/users/{user.user_id}").status_code == 404


def test_reset_link(admin: TestClient, user: TestClient, fake_clock):
    r = admin.post(f"/api/admin/users/{user.user_id}/reset")
    body = r.json()
    assert r.status_code == 200 and body["url"].startswith(f"{BASE_URL}/reset/")
    assert body["expires_at"] == fake_clock.t + accounts.RESET_TTL
    assert admin.post("/api/admin/users/9999/reset").status_code == 404


def test_invites(admin: TestClient, make_client, fake_clock):
    r = admin.post("/api/admin/invites", json={"email": "  Masha@Example.ORG ", "quota": 50 * GiB, "note": "игнор"})
    assert r.status_code == 201
    inv = r.json()
    assert inv["url"].startswith(f"{BASE_URL}/invite/") and inv["email"] == "masha@example.org"
    assert set(inv) == {"id", "email", "quota", "created_at", "expires_at", "url"}
    assert inv["quota"] == 50 * GiB
    assert inv["expires_at"] == fake_clock.t + accounts.INVITE_TTL
    # no quota given — from settings; null — unlimited
    free = admin.post("/api/admin/invites", json={"email": "petya@example.com"}).json()
    assert (free["email"], free["quota"]) == ("petya@example.com", GiB)
    unl = admin.post("/api/admin/invites", json={"email": "vasya@example.com", "quota": None}).json()
    assert unl["quota"] is None
    assert admin.delete(f"/api/admin/invites/{unl['id']}").status_code == 204

    listed = admin.get("/api/admin/invites").json()["invites"]
    assert [i["id"] for i in listed] == [free["id"], inv["id"]]
    assert "url" not in listed[0]
    assert set(listed[0]) == {"id", "email", "quota", "created_at", "expires_at"}

    # used and expired invites leave the list
    token = free["url"].rsplit("/", 1)[1]
    c = make_client(EXTERNAL_IP)
    assert c.post(f"/api/auth/tokens/{token}", json={"login": "newbie", "password": USER_PASSWORD}).status_code == 204
    assert [i["id"] for i in admin.get("/api/admin/invites").json()["invites"]] == [inv["id"]]
    assert admin.delete(f"/api/admin/invites/{free['id']}").status_code == 404  # already used
    assert _user(admin, "newbie")["email"] == "petya@example.com"
    assert _user(admin, "newbie")["quota"] == GiB

    assert admin.delete(f"/api/admin/invites/{inv['id']}").status_code == 204
    assert admin.get("/api/admin/invites").json()["invites"] == []
    token = inv["url"].rsplit("/", 1)[1]
    assert c.get(f"/api/auth/tokens/{token}").status_code == 404
    assert admin.delete(f"/api/admin/invites/{inv['id']}").status_code == 404

    late = admin.post("/api/admin/invites", json={"email": "late@example.com"}).json()
    fake_clock.advance(accounts.INVITE_TTL)
    assert late["id"] not in [i["id"] for i in admin.get("/api/admin/invites").json()["invites"]]


def test_invite_validation(admin: TestClient, user: TestClient):
    for body in ({}, {"email": ""}, {"email": "masha"}, {"email": 5}, {"note": "Маша"}):
        r = admin.post("/api/admin/invites", json=body)
        assert r.status_code == 400 and r.json()["error"] == "bad_email", body
    for bad in (0, -5, 1.5, "1", True):
        r = admin.post("/api/admin/invites", json={"email": "m@example.com", "quota": bad})
        assert r.status_code == 400 and r.json()["error"] == "bad_quota", bad
    # a user with this email exists (alice — alice@example.com, the owner — from settings)
    for email in ("ALICE@example.com", "admin@example.com"):
        r = admin.post("/api/admin/invites", json={"email": email})
        assert r.status_code == 409 and r.json() == {
            "error": "email_taken", "message": "This email is already registered"}, email
    assert admin.get("/api/admin/invites").json()["invites"] == []


def test_reinvite_replaces_unused_invite(admin: TestClient, make_client, fake_clock):
    c = make_client(EXTERNAL_IP)
    first = admin.post("/api/admin/invites", json={"email": "masha@example.com", "quota": 50 * GiB}).json()
    fake_clock.advance(DAY)
    second = admin.post("/api/admin/invites", json={"email": "Masha@Example.com"}).json()
    assert second["quota"] == GiB and second["url"] != first["url"]
    assert c.get(f"/api/auth/tokens/{first['url'].rsplit('/', 1)[1]}").status_code == 404
    assert [(i["email"], i["quota"]) for i in admin.get("/api/admin/invites").json()["invites"]] == [
        ("masha@example.com", GiB)]
    # an expired unused invite is replaced too, not piled up
    fake_clock.advance(accounts.INVITE_TTL)
    third = admin.post("/api/admin/invites", json={"email": "masha@example.com"}).json()
    assert c.get(f"/api/auth/tokens/{second['url'].rsplit('/', 1)[1]}").status_code == 404
    assert [i["expires_at"] for i in admin.get("/api/admin/invites").json()["invites"]] == [third["expires_at"]]
    # another email is left alone
    admin.post("/api/admin/invites", json={"email": "petya@example.com"})
    assert sorted(i["email"] for i in admin.get("/api/admin/invites").json()["invites"]) == [
        "masha@example.com", "petya@example.com"]


def test_renew_invite(admin: TestClient, make_client, fake_clock):
    inv = admin.post("/api/admin/invites", json={"email": "masha@example.com", "quota": 50 * GiB}).json()
    fake_clock.advance(5 * DAY)
    r = admin.post(f"/api/admin/invites/{inv['id']}/renew")
    assert r.status_code == 200
    renewed = r.json()
    assert set(renewed) == {"id", "email", "quota", "created_at", "expires_at", "url"}
    assert (renewed["id"], renewed["email"], renewed["quota"]) == (inv["id"], "masha@example.com", 50 * GiB)
    assert renewed["expires_at"] == fake_clock.t + accounts.INVITE_TTL
    assert renewed["url"] != inv["url"] and renewed["url"].startswith(f"{BASE_URL}/invite/")
    c = make_client(EXTERNAL_IP)
    assert c.get(f"/api/auth/tokens/{inv['url'].rsplit('/', 1)[1]}").status_code == 404
    new = renewed["url"].rsplit("/", 1)[1]
    assert c.get(f"/api/auth/tokens/{new}").status_code == 200
    assert [i["expires_at"] for i in admin.get("/api/admin/invites").json()["invites"]] == [renewed["expires_at"]]

    # expired but unused — comes back to life
    fake_clock.advance(accounts.INVITE_TTL + DAY)
    assert admin.get("/api/admin/invites").json()["invites"] == []
    again = admin.post(f"/api/admin/invites/{inv['id']}/renew").json()
    assert again["expires_at"] == fake_clock.t + accounts.INVITE_TTL
    token = again["url"].rsplit("/", 1)[1]
    assert c.post(f"/api/auth/tokens/{token}", json={"login": "masha", "password": USER_PASSWORD}).status_code == 204
    assert _user(admin, "masha")["quota"] == 50 * GiB

    # used and missing — 404
    r = admin.post(f"/api/admin/invites/{inv['id']}/renew")
    assert r.status_code == 404 and r.json()["error"] == "not_found"
    assert admin.post("/api/admin/invites/9999/renew").status_code == 404


ROUTES = [
    ("GET", "/api/admin/users"),
    ("PATCH", "/api/admin/users/1"),
    ("DELETE", "/api/admin/users/1"),
    ("POST", "/api/admin/users/1/reset"),
    ("GET", "/api/admin/invites"),
    ("POST", "/api/admin/invites"),
    ("DELETE", "/api/admin/invites/1"),
    ("POST", "/api/admin/invites/1/renew"),
]


def test_not_admin_forbidden(make_user, admin: TestClient):
    inside = make_user("carol", ip=INTERNAL_IP)
    for method, path in ROUTES:
        r = inside.request(method, path, json={})
        assert r.status_code == 403 and r.json()["error"] == "forbidden", (method, path)


def test_admin_outside_forbidden(admin: TestClient, make_client):
    outside = make_client(EXTERNAL_IP)
    outside.cookies.set("share_session", admin.cookies.get("share_session"), domain="share.test")
    for method, path in ROUTES:
        r = outside.request(method, path, json={})
        assert r.status_code == 403 and r.json()["error"] == "forbidden", (method, path)
    assert admin.get("/api/admin/users").status_code == 200


def test_no_session_unauthenticated(anon: TestClient):
    for method, path in ROUTES:
        r = anon.request(method, path, json={})
        assert r.status_code == 401 and r.json()["error"] == "unauthenticated", (method, path)
