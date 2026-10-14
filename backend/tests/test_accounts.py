from __future__ import annotations

import asyncio
import hashlib

import anyio
import httpx2 as httpx
import pytest
from starlette.testclient import TestClient

from share_app import accounts, clock
from share_app.auth import verify_password
from share_app.errors import ApiError
from share_app.quota import GiB
from tests.conftest import (
    ADMIN_EMAIL,
    BASE_URL,
    EXTERNAL_IP,
    USER_HASH,
    USER_PASSWORD,
)

DAY = 86400


ALICE = "alice@example.com"


def _login(c: TestClient, email: str = ALICE, password: str = USER_PASSWORD):
    return c.post("/api/auth/login", json={"email": email, "password": password})


def _alice(ctx) -> int:
    return ctx.db.create_user(login="alice", email=ALICE, password_hash=USER_HASH, quota_bytes=GiB,
                              created_at=clock.now())


def _invite(admin: TestClient, email: str = "new@example.com", **body) -> str:
    r = admin.post("/api/admin/invites", json={"email": email, **body})
    assert r.status_code == 201, r.text
    return r.json()["url"].rsplit("/", 1)[1]


def _reset(admin: TestClient, user_id: int) -> str:
    r = admin.post(f"/api/admin/users/{user_id}/reset")
    assert r.status_code == 200, r.text
    return r.json()["url"].rsplit("/", 1)[1]


# --- sign-in ---

def test_login_sets_session(ctx, make_client):
    uid = _alice(ctx)
    c = make_client(EXTERNAL_IP)
    r = _login(c, email="  Alice@Example.COM ")
    assert r.status_code == 204
    cookie = r.headers["set-cookie"]
    assert "share_session=" in cookie and "HttpOnly" in cookie and "Secure" in cookie and "Path=/" in cookie
    assert "samesite=lax" in cookie.lower() and "Max-Age=2592000" in cookie
    # the DB holds only sha256 of the token
    token = c.cookies.get("share_session")
    [session] = ctx.db.user_sessions(uid)
    assert session["token_hash"] == hashlib.sha256(token.encode()).hexdigest() != token
    assert c.get("/api/auth/session").json() == {"authenticated": True, "user": {
        "login": "alice", "email": ALICE, "role": "user", "quota": GiB, "used": 0, "admin_panel": False,
    }}
    assert ctx.db.get_user(uid)["last_login_at"] is not None


def test_wrong_login_and_password_look_the_same(ctx, make_client):
    _alice(ctx)
    c = make_client(EXTERNAL_IP)
    a = _login(c, password="wrong-password")
    b = _login(c, email="nobody@example.com")
    assert a.status_code == b.status_code == 403
    assert a.json() == b.json() == {"error": "wrong_credentials", "message": "Wrong email or password"}
    assert _login(c, email="bad email!").json()["error"] == "wrong_credentials"
    assert c.post("/api/auth/login", json={"email": ALICE}).json()["error"] == "wrong_credentials"


def test_login_by_username_no_longer_works(ctx, make_client):
    _alice(ctx)
    c = make_client(EXTERNAL_IP)
    r = c.post("/api/auth/login", json={"login": "alice", "password": USER_PASSWORD})
    assert r.status_code == 403 and r.json()["error"] == "wrong_credentials"
    assert _login(c, email="alice").json()["error"] == "wrong_credentials"
    assert _login(c).status_code == 204


def test_user_without_email_cannot_login(ctx, make_client):
    """Owner without an email: has a password but no email — cannot sign in."""
    ctx.db.create_user(login="noemail", password_hash=USER_HASH, quota_bytes=GiB, created_at=clock.now())
    c = make_client(EXTERNAL_IP)
    assert c.post("/api/auth/login", json={"email": "", "password": USER_PASSWORD}).json()["error"] == \
        "wrong_credentials"
    assert c.post("/api/auth/login", json={"email": None, "password": USER_PASSWORD}).json()["error"] == \
        "wrong_credentials"


def test_owner_without_password_cannot_login(ctx, make_client):
    """Owner without a password hash exists, but no password signs in."""
    ctx.db.update_user(ctx.db.get_user_by_login("admin")["id"], password_hash="")
    c = make_client()
    assert _login(c, ADMIN_EMAIL, "dummy-password-for-timing").json()["error"] == "wrong_credentials"
    assert _login(c, ADMIN_EMAIL, "").json()["error"] == "wrong_credentials"


def test_blocked_only_with_right_password(ctx, make_client):
    uid = _alice(ctx)
    ctx.db.update_user(uid, blocked_at=clock.now())
    c = make_client(EXTERNAL_IP)
    assert _login(c, password="wrong-password").json()["error"] == "wrong_credentials"
    r = _login(c)
    assert r.status_code == 403 and r.json()["error"] == "blocked"
    assert "set-cookie" not in r.headers


def test_rate_limit_by_ip(ctx, make_client):
    _alice(ctx)
    c = make_client(EXTERNAL_IP)
    for i in range(5):
        assert _login(c, email=f"user{i}@example.com", password="x").status_code == 403
    r = _login(c)
    assert r.status_code == 429 and r.json()["error"] == "too_many_attempts" and r.json()["retry_after"] == 900
    # from another address — allowed
    assert _login(make_client("203.0.113.99")).status_code == 204


def test_rate_limit_by_email(ctx, make_client):
    _alice(ctx)
    for i in range(10):
        # case and spaces — the same key
        email = ALICE.upper() if i % 2 else f" {ALICE} "
        assert _login(make_client(f"198.51.100.{i}"), email=email, password="x").status_code == 403
    r = _login(make_client("198.51.100.200"))
    assert r.status_code == 429 and r.json()["error"] == "too_many_attempts"
    # another email from the same address is not affected
    assert _login(make_client("198.51.100.200"), email="nobody@example.com", password="x").status_code == 403


def test_success_resets_ip_limit(ctx, make_client):
    _alice(ctx)
    c = make_client(EXTERNAL_IP)
    for _ in range(4):
        _login(c, password="x")
    assert _login(c).status_code == 204
    for _ in range(4):
        assert _login(c, password="x").status_code == 403


# --- session ---

def test_session_expires(user: TestClient, fake_clock):
    assert user.get("/api/app/shares").status_code == 200
    fake_clock.advance(accounts.SESSION_TTL)
    assert user.get("/api/app/shares").status_code == 401
    assert user.get("/api/auth/session").json() == {"authenticated": False}


def test_session_touch_throttled(user: TestClient, ctx, fake_clock):
    [s] = ctx.db.user_sessions(user.user_id)
    fake_clock.advance(60)
    user.get("/api/auth/session")
    assert ctx.db.user_sessions(user.user_id)[0]["last_seen_at"] == s["last_seen_at"]
    fake_clock.advance(accounts.TOUCH_EVERY)
    user.get("/api/auth/session")
    assert ctx.db.user_sessions(user.user_id)[0]["last_seen_at"] == fake_clock.t


def test_logout(user: TestClient, make_client, ctx):
    token = user.cookies.get("share_session")
    r = user.post("/api/auth/logout")
    assert r.status_code == 204 and 'share_session=""' in r.headers["set-cookie"]
    assert ctx.db.user_sessions(user.user_id) == []
    # the old token opens nothing anymore
    c = make_client(EXTERNAL_IP)
    c.cookies.set("share_session", token, domain="share.test")
    assert c.get("/api/app/shares").status_code == 401
    # signing out without a session — 204 too
    assert make_client().post("/api/auth/logout").status_code == 204


def test_logout_all(ctx, make_client):
    _alice(ctx)
    a, b = make_client(EXTERNAL_IP), make_client("203.0.113.7")
    assert _login(a).status_code == 204 and _login(b).status_code == 204
    assert a.post("/api/auth/logout-all").status_code == 204
    assert a.get("/api/app/shares").status_code == 401
    assert b.get("/api/app/shares").status_code == 401
    assert make_client().post("/api/auth/logout-all").status_code == 401


def test_change_password(ctx, make_client):
    uid = _alice(ctx)
    a, b = make_client(EXTERNAL_IP), make_client("203.0.113.7")
    _login(a), _login(b)
    r = a.post("/api/auth/password", json={"current": "wrong-password", "new": "new-password-123"})
    assert r.status_code == 403 and r.json()["error"] == "wrong_password"
    r = a.post("/api/auth/password", json={"current": USER_PASSWORD, "new": "short"})
    assert r.status_code == 400 and r.json() == {
        "error": "weak_password", "message": "Password must be at least 10 characters",
        "min_length": 10, "max_length": 200,
    }
    r = a.post("/api/auth/password", json={"current": USER_PASSWORD, "new": "x" * 201})
    assert r.status_code == 400 and r.json()["error"] == "weak_password"
    assert a.post("/api/auth/password", json={"current": USER_PASSWORD, "new": "new-password-123"}).status_code == 204
    # the current session lives, the other one is revoked
    assert a.get("/api/app/shares").status_code == 200
    assert b.get("/api/app/shares").status_code == 401
    assert verify_password("new-password-123", ctx.db.get_user(uid)["password_hash"])
    assert _login(make_client("203.0.113.8")).status_code == 403
    assert _login(make_client("203.0.113.8"), password="new-password-123").status_code == 204


# --- invites ---

def test_invite_flow(admin: TestClient, make_client, ctx, fake_clock):
    token = _invite(admin, " Masha@Example.ORG ", quota=50 * GiB)
    c = make_client(EXTERNAL_IP)
    assert c.get(f"/api/auth/tokens/{token}").json() == {"kind": "invite", "email": "masha@example.org", "login": None}
    # the email comes from the invite: one sent in the body is ignored
    r = c.post(f"/api/auth/tokens/{token}", json={"login": "  Masha.K ", "password": USER_PASSWORD,
                                                  "email": "evil@example.com"})
    assert r.status_code == 204 and "share_session=" in r.headers["set-cookie"]
    me = c.get("/api/auth/session").json()["user"]
    assert me["login"] == "masha.k" and me["email"] == "masha@example.org"
    assert me["quota"] == 50 * GiB
    user = ctx.db.get_user_by_login("masha.k")
    assert user["quota_bytes"] == 50 * GiB
    # sign-up signs in right away — that is the first sign-in, not "never signed in"
    assert user["last_login_at"] == fake_clock.t
    # signing in by email and password works, by username does not
    assert _login(make_client("203.0.113.9"), "MASHA@example.org").status_code == 204
    assert _login(make_client("203.0.113.9"), "masha.k").status_code == 403

    # a repeat — both reading and accepting — is 410; no second account
    other = make_client("203.0.113.10")
    r = other.get(f"/api/auth/tokens/{token}")
    assert r.status_code == 410 and r.json()["error"] == "token_expired"
    r = other.post(f"/api/auth/tokens/{token}", json={"login": "masha2", "password": USER_PASSWORD})
    assert r.status_code == 410
    assert ctx.db.get_user_by_login("masha2") is None


def test_invite_quota_default_and_unlimited(admin: TestClient, make_client):
    token = _invite(admin)
    c = make_client(EXTERNAL_IP)
    assert c.get(f"/api/auth/tokens/{token}").json() == {"kind": "invite", "email": "new@example.com", "login": None}
    assert c.post(f"/api/auth/tokens/{token}", json={"login": "free1", "password": USER_PASSWORD}).status_code == 204
    assert c.get("/api/auth/session").json()["user"]["quota"] == GiB
    token = _invite(admin, "big@example.com", quota=None)
    c = make_client("203.0.113.11")
    assert c.post(f"/api/auth/tokens/{token}", json={"login": "big1", "password": USER_PASSWORD}).status_code == 204
    assert c.get("/api/auth/session").json()["user"]["quota"] is None


def test_invite_expires(admin: TestClient, make_client, fake_clock):
    token = _invite(admin)
    fake_clock.advance(accounts.INVITE_TTL)
    c = make_client(EXTERNAL_IP)
    assert c.get(f"/api/auth/tokens/{token}").status_code == 410
    r = c.post(f"/api/auth/tokens/{token}", json={"login": "late", "password": USER_PASSWORD})
    assert r.status_code == 410 and r.json()["error"] == "token_expired"


def test_invite_validation(admin: TestClient, make_client, ctx):
    token = _invite(admin)
    c = make_client(EXTERNAL_IP)
    url = f"/api/auth/tokens/{token}"
    r = c.post(url, json={"login": "ADMIN", "password": USER_PASSWORD})
    assert r.status_code == 409 and r.json()["error"] == "login_taken"
    for bad in ("ab", "x" * 33, "имя", "a b", None, 5):
        r = c.post(url, json={"login": bad, "password": USER_PASSWORD})
        assert r.status_code == 400 and r.json()["error"] == "bad_login", bad
        assert (r.json()["min_length"], r.json()["max_length"]) == (3, 32)
    r = c.post(url, json={"login": "newbie", "password": "123456789"})
    assert r.status_code == 400 and r.json()["error"] == "weak_password"
    # refusals do not use up the invite
    assert c.post(url, json={"login": "newbie", "password": USER_PASSWORD}).status_code == 204
    assert c.get("/api/auth/tokens/nonexistent-token").status_code == 404
    assert c.post("/api/auth/tokens/nonexistent-token", json={}).status_code == 404


def test_invite_email_taken_on_accept(admin: TestClient, make_client, ctx):
    """The email got taken while the invite waited (e.g. set-email) — 409, the invite is not used up."""
    token = _invite(admin, "late@example.com")
    uid = _alice(ctx)
    with ctx.db.transaction() as conn:
        conn.execute("UPDATE users SET email = 'late@example.com' WHERE id = ?", (uid,))
    c = make_client(EXTERNAL_IP)
    r = c.post(f"/api/auth/tokens/{token}", json={"login": "late", "password": USER_PASSWORD})
    assert r.status_code == 409 and r.json() == {"error": "email_taken", "message": "This email is already registered"}
    assert ctx.db.get_user_by_login("late") is None
    assert c.get(f"/api/auth/tokens/{token}").status_code == 200


def test_reinvite_same_email_replaces_link(admin: TestClient, make_client, ctx):
    old = _invite(admin, "masha@example.com", quota=50 * GiB)
    new = _invite(admin, "MASHA@example.com")
    c = make_client(EXTERNAL_IP)
    assert c.get(f"/api/auth/tokens/{old}").status_code == 404
    r = c.post(f"/api/auth/tokens/{old}", json={"login": "masha", "password": USER_PASSWORD})
    assert r.status_code == 404
    assert c.post(f"/api/auth/tokens/{new}", json={"login": "masha", "password": USER_PASSWORD}).status_code == 204
    assert c.get("/api/auth/session").json()["user"]["quota"] == GiB
    assert [i["email"] for i in admin.get("/api/admin/invites").json()["invites"]] == []


def test_renewed_invite_old_link_dead(admin: TestClient, make_client, fake_clock):
    r = admin.post("/api/admin/invites", json={"email": "masha@example.com", "quota": 50 * GiB})
    inv = r.json()
    old = inv["url"].rsplit("/", 1)[1]
    fake_clock.advance(3 * DAY)
    renewed = admin.post(f"/api/admin/invites/{inv['id']}/renew").json()
    new = renewed["url"].rsplit("/", 1)[1]
    assert new != old
    c = make_client(EXTERNAL_IP)
    assert c.get(f"/api/auth/tokens/{old}").status_code == 404
    assert c.get(f"/api/auth/tokens/{new}").json() == {"kind": "invite", "email": "masha@example.com", "login": None}
    assert c.post(f"/api/auth/tokens/{new}", json={"login": "masha", "password": USER_PASSWORD}).status_code == 204
    assert c.get("/api/auth/session").json()["user"]["email"] == "masha@example.com"


def test_invite_race_single_winner(app, admin: TestClient, ctx):
    token = _invite(admin)

    async def run():
        transport = httpx.ASGITransport(app=app, client=(EXTERNAL_IP, 1))
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL, headers={"Origin": BASE_URL}) as c:
            return await asyncio.gather(*(
                c.post(f"/api/auth/tokens/{token}", json={"login": f"racer{i}", "password": USER_PASSWORD})
                for i in range(2)
            ))

    results = anyio.run(run)
    assert sorted(r.status_code for r in results) == [204, 410]
    assert sum(ctx.db.get_user_by_login(f"racer{i}") is not None for i in range(2)) == 1


# --- password reset ---

def test_reset_password(admin: TestClient, user: TestClient, make_client, ctx):
    token = _reset(admin, user.user_id)
    c = make_client("203.0.113.20")
    assert c.get(f"/api/auth/tokens/{token}").json() == {
        "kind": "reset", "email": "alice@example.com", "login": "alice"}
    r = c.post(f"/api/auth/tokens/{token}", json={"password": "short"})
    assert r.status_code == 400 and r.json()["error"] == "weak_password"
    assert c.post(f"/api/auth/tokens/{token}", json={"password": "brand-new-password"}).status_code == 204
    assert c.get("/api/auth/session").json()["user"]["login"] == "alice"
    assert ctx.db.get_user_by_login("alice")["last_login_at"] is not None
    # old sessions are revoked, the old password does not work
    assert user.get("/api/app/shares").status_code == 401
    assert _login(make_client("203.0.113.21")).status_code == 403
    assert _login(make_client("203.0.113.22"), password="brand-new-password").status_code == 204
    assert c.post(f"/api/auth/tokens/{token}", json={"password": "another-password"}).status_code == 410


def test_reset_expires(admin: TestClient, user: TestClient, make_client, fake_clock):
    token = _reset(admin, user.user_id)
    fake_clock.advance(accounts.RESET_TTL)
    assert make_client().get(f"/api/auth/tokens/{token}").status_code == 410


def test_tokens_stored_hashed(admin: TestClient, ctx):
    token = _invite(admin)
    with ctx.db.transaction() as conn:
        stored = [r[0] for r in conn.execute("SELECT token_hash FROM tokens")]
    assert stored == [hashlib.sha256(token.encode()).hexdigest()]


def test_normalize_email():
    assert accounts.normalize_email("  Masha@Example.ORG ") == "masha@example.org"
    for bad in ("", "masha", "masha@example", "@example.org", "ma sha@example.org", "a@b@c.ru", None, 5,
                "x" * 250 + "@example.org"):
        with pytest.raises(ApiError) as exc:
            accounts.normalize_email(bad)
        assert exc.value.code == "bad_email" and exc.value.status == 400, bad
