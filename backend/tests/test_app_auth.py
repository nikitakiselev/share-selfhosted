"""Connecting the desktop app: a one-time code issued in the browser is exchanged for a
session token (PKCE), which the app then sends as `Authorization: Bearer`."""

from __future__ import annotations

import base64
import hashlib
import secrets

from starlette.testclient import TestClient

from share_app import accounts
from tests.conftest import EXTERNAL_IP, new_share


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _connect(user: TestClient, make_client, verifier: str | None = None) -> tuple[str, TestClient]:
    """The browser (with a session) issues a code; the app (no cookies, no Origin) exchanges it."""
    verifier, challenge = (verifier, _pkce()[1]) if verifier else _pkce()
    r = user.post("/api/auth/app/connect", json={"challenge": challenge})
    assert r.status_code == 200, r.text
    code = r.json()["code"]
    app = make_client(EXTERNAL_IP, origin=False)
    r = app.post("/api/auth/app/token", json={"code": code, "verifier": verifier})
    assert r.status_code == 200, r.text
    body = r.json()
    app.headers["Authorization"] = f"Bearer {body['token']}"
    return body["token"], app


def test_connect_flow(user: TestClient, make_client, ctx):
    token, app = _connect(user, make_client)
    # the DB holds only the hash, like for a cookie session
    hashes = {s["token_hash"] for s in ctx.db.user_sessions(user.user_id)}
    assert accounts.token_hash(token) in hashes and token not in hashes
    s = app.get("/api/auth/session").json()
    assert s["authenticated"] and s["user"]["login"] == "alice"
    # state-changing requests work without Origin: there is no cookie, nothing to forge
    share = new_share(app)
    assert app.get(f"/api/app/shares/{share['slug']}").status_code == 200
    # the app signs out like a browser does
    assert app.post("/api/auth/logout").status_code == 204
    assert app.get("/api/auth/session").json() == {"authenticated": False}


def test_code_is_single_use_and_bound_to_verifier(user: TestClient, make_client):
    verifier, challenge = _pkce()
    code = user.post("/api/auth/app/connect", json={"challenge": challenge}).json()["code"]
    app = make_client(EXTERNAL_IP, origin=False)
    r = app.post("/api/auth/app/token", json={"code": code, "verifier": "wrong-verifier"})
    assert r.status_code == 403 and r.json()["error"] == "bad_code"
    # a wrong attempt burns the code: whoever intercepted it cannot keep guessing
    r = app.post("/api/auth/app/token", json={"code": code, "verifier": verifier})
    assert r.status_code == 403

    code = user.post("/api/auth/app/connect", json={"challenge": challenge}).json()["code"]
    assert app.post("/api/auth/app/token", json={"code": code, "verifier": verifier}).status_code == 200
    assert app.post("/api/auth/app/token", json={"code": code, "verifier": verifier}).status_code == 403


def test_code_expires(user: TestClient, make_client, fake_clock):
    verifier, challenge = _pkce()
    code = user.post("/api/auth/app/connect", json={"challenge": challenge}).json()["code"]
    fake_clock.advance(accounts.APP_CODE_TTL)
    app = make_client(EXTERNAL_IP, origin=False)
    assert app.post("/api/auth/app/token", json={"code": code, "verifier": verifier}).status_code == 403


def test_connect_requires_session_and_valid_challenge(anon: TestClient, user: TestClient):
    assert anon.post("/api/auth/app/connect", json={"challenge": _pkce()[1]}).status_code == 401
    for bad in ("", "short", "x" * 43 + "!", 42):
        r = user.post("/api/auth/app/connect", json={"challenge": bad})
        assert r.status_code == 400 and r.json()["error"] == "bad_challenge", bad


def test_token_exchange_rate_limited(make_client):
    app = make_client(EXTERNAL_IP, origin=False)
    for _ in range(10):
        assert app.post("/api/auth/app/token", json={"code": "nope", "verifier": "x"}).status_code == 403
    r = app.post("/api/auth/app/token", json={"code": "nope", "verifier": "x"})
    assert r.status_code == 429 and r.json()["error"] == "too_many_attempts"


def test_bearer_token_invalid(make_client):
    app = make_client(EXTERNAL_IP, origin=False, headers={"Authorization": "Bearer nope"})
    assert app.get("/api/auth/session").json() == {"authenticated": False}
    assert app.get("/api/app/shares").status_code == 401
    assert make_client(EXTERNAL_IP, origin=False, headers={"Authorization": "Basic abc"}).get(
        "/api/app/shares").status_code == 401


def test_bearer_with_foreign_origin_refused(user: TestClient, make_client):
    _, app = _connect(user, make_client)
    r = app.post("/api/app/shares", json={}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"] == "bad_origin"


def test_blocked_user_cannot_exchange(user: TestClient, make_client, ctx):
    verifier, challenge = _pkce()
    code = user.post("/api/auth/app/connect", json={"challenge": challenge}).json()["code"]
    ctx.db.update_user(user.user_id, blocked_at=1)
    app = make_client(EXTERNAL_IP, origin=False)
    r = app.post("/api/auth/app/token", json={"code": code, "verifier": verifier})
    assert r.status_code == 403 and r.json()["error"] == "blocked"
