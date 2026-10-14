from __future__ import annotations

from starlette.testclient import TestClient

from tests.conftest import EXTERNAL_IP, new_share


def test_external_gets_403_only_on_admin(outsider: TestClient):
    for path in ("/api/admin/users", "/api/admin/invites", "/api/admin", "/api/admin/nope"):
        r = outsider.get(path)
        assert r.status_code == 403, path
        assert r.json()["error"] == "forbidden"
    assert outsider.post("/api/admin/invites", json={}).status_code == 403


def test_external_reaches_everything_else(outsider: TestClient):
    assert outsider.get("/healthz").json() == {"ok": True}
    assert outsider.get("/api/public/shares/nope").status_code == 404
    assert outsider.get("/s/nope").status_code == 200
    assert outsider.get("/assets/app.js").status_code == 200
    assert outsider.get("/favicon.svg").status_code == 200
    for path in ("/", "/shares", "/users", "/invite/x"):
        assert outsider.get(path).status_code == 200, path
    assert outsider.get("/api/auth/session").json() == {"authenticated": False}
    r = outsider.get("/api/app/shares")
    assert r.status_code == 401 and r.json()["error"] == "unauthenticated"


def test_xff_from_trusted_proxy(make_client):
    caddy = make_client("192.168.1.2")
    assert caddy.get("/api/admin/users", headers={"X-Forwarded-For": EXTERNAL_IP}).status_code == 403
    # inside without a session — 401 from the app, not 403 from the network
    assert caddy.get("/api/admin/users", headers={"X-Forwarded-For": "10.8.0.2"}).status_code == 401


def test_spoofed_xff_ignored(outsider: TestClient):
    r = outsider.get("/api/admin/users", headers={"X-Forwarded-For": "192.168.1.10"})
    assert r.status_code == 403


def test_stolen_admin_cookie_useless_outside(admin: TestClient, make_client):
    token = admin.cookies.get("share_session")
    outside = make_client(EXTERNAL_IP)
    outside.cookies.set("share_session", token, domain="share.test")
    assert outside.get("/api/admin/users").status_code == 403
    session = outside.get("/api/auth/session").json()
    assert session["authenticated"] and session["user"]["admin_panel"] is False
    assert admin.get("/api/auth/session").json()["user"]["admin_panel"] is True


def test_origin_required_with_session(admin: TestClient, make_client):
    r = admin.post("/api/app/shares", json={}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"] == "bad_origin"
    assert admin.post("/api/app/shares", json={}, headers={"Origin": "null"}).status_code == 403
    assert admin.post("/api/app/shares", json={}).status_code == 201
    # no Origin but a cookie — refused too: that is what a foreign form looks like in an old browser
    bare = make_client(origin=False)
    bare.cookies.set("share_session", admin.cookies.get("share_session"), domain="share.test")
    r = bare.post("/api/app/shares", json={})
    assert r.status_code == 403 and r.json()["error"] == "bad_origin"
    assert bare.post("/api/auth/logout").status_code == 403
    # reads without Origin are fine
    assert bare.get("/api/app/shares").status_code == 200


def test_origin_optional_without_session(make_client, admin: TestClient):
    bare = make_client(origin=False)
    assert bare.post("/api/auth/login", json={"email": "x@example.com", "password": "y"}).json()["error"] == "wrong_credentials"
    slug = new_share(admin, password="pw")["slug"]
    assert bare.post(f"/api/public/shares/{slug}/unlock", json={"password": "pw"}).status_code == 204
    evil = make_client(origin=False, headers={"Origin": "https://evil.example"})
    assert evil.post("/api/auth/login", json={"email": "x@example.com", "password": "y"}).status_code == 403


def test_same_host_origin_allowed(make_client, admin: TestClient):
    """Local runs and access by IP: Origin matches the request Host."""
    c = make_client(origin=False, headers={"Origin": "http://192.168.1.121:8000", "Host": "192.168.1.121:8000"})
    c.cookies.set("share_session", admin.cookies.get("share_session"))
    assert c.post("/api/app/shares", json={}).status_code == 201


def test_unknown_path_is_json_404(anon: TestClient):
    r = anon.get("/api/app/nope")
    assert r.status_code == 404 and r.json()["error"] == "not_found"
