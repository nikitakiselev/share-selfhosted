"""Sign-in and account: session, email sign-in, sign-out, password change, invites and resets.

Open to the internet. A wrong email and a wrong password get the same answer in the same
time — the response does not reveal whether such a user exists.
"""

from __future__ import annotations

import logging
from functools import cache
from typing import Any

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from share_app import accounts, auth, clock
from share_app.context import Context
from share_app.errors import ApiError, json_body, too_many_attempts
from share_app.quota import usage

log = logging.getLogger("share")


def _ctx(request: Request) -> Context:
    return request.app.state.ctx


@cache
def _dummy_hash() -> str:
    # scrypt runs even for an unknown email — otherwise the response time would give it away
    return auth.hash_password("dummy-password-for-timing")


async def _verify(password: object, encoded: str | None) -> bool:
    """No user or no password set — scrypt still runs against a dummy hash, but the result
    is always False."""
    if not isinstance(password, str):
        return False
    if not encoded:
        await anyio.to_thread.run_sync(lambda: auth.verify_password(password, _dummy_hash()))
        return False
    return await anyio.to_thread.run_sync(auth.verify_password, password, encoded)


def _login_response(ctx: Context, request: Request, user_id: int) -> Response:
    """A new session is a sign-in wherever it comes from: password, invite, reset."""
    now = clock.now()
    token = accounts.create_session(ctx.db, user_id, now, ctx.client_ip(request), request.headers.get("user-agent"))
    ctx.db.update_user(user_id, last_login_at=now)
    resp = Response(status_code=204)
    ctx.set_session_cookie(resp, token)
    return resp


def session_body(ctx: Context, request: Request, user: dict[str, Any]) -> dict[str, Any]:
    u = usage(ctx.db, user)
    return {
        "login": user["login"],
        "email": user["email"],
        "role": user["role"],
        "quota": u["quota"],
        "used": u["used"],
        "admin_panel": user["role"] == "admin" and ctx.is_internal(request),
    }


async def session(request: Request) -> JSONResponse:
    ctx = _ctx(request)
    user = ctx.current_user(request)
    if user is None:
        return JSONResponse({"authenticated": False}, headers={"Cache-Control": "no-store"})
    return JSONResponse({"authenticated": True, "user": session_body(ctx, request, user)},
                        headers={"Cache-Control": "no-store"})


async def login(request: Request) -> Response:
    ctx = _ctx(request)
    now = clock.now()
    ip = ctx.client_ip(request)
    data = await json_body(request)
    raw_email = data.get("email")
    email_key = raw_email.strip().lower()[:accounts.EMAIL_MAX] if isinstance(raw_email, str) else ""
    if ctx.login_limiter.blocked(ip, now) or (email_key and ctx.login_user_limiter.blocked(email_key, now)):
        raise too_many_attempts()
    user = ctx.db.get_user_by_email(email_key) if email_key else None
    ok = await _verify(data.get("password"), user["password_hash"] if user else None)
    if not ok or user is None:
        ctx.login_limiter.hit(ip, now)
        if email_key:
            ctx.login_user_limiter.hit(email_key, now)
        # what does not look like an email stays out of the log: people type passwords there by mistake
        shown = email_key if accounts.is_email(email_key) else "(not an email)"
        log.warning("failed sign-in: email %r, IP %s", shown, ip)
        raise ApiError(403, "wrong_credentials", "Wrong email or password")
    if user["blocked_at"] is not None:
        log.warning("sign-in of blocked user %s, IP %s", user["login"], ip)
        raise ApiError(403, "blocked", "Account is blocked")
    ctx.login_limiter.reset(ip)
    ctx.login_user_limiter.reset(email_key)
    log.info("sign-in: %s (%s), IP %s", user["login"], user["email"], ip)
    return _login_response(ctx, request, user["id"])


# --- desktop app ---

async def app_connect(request: Request) -> JSONResponse:
    """The `/connect` page: a signed-in browser asks for a one-time code for the desktop app."""
    ctx = _ctx(request)
    user = ctx.require_user(request)
    data = await json_body(request)
    challenge = accounts.normalize_challenge(data.get("challenge"))
    code = accounts.issue_app_code(ctx.app_codes, user["id"], challenge, clock.now())
    log.info("app connect code issued: %s, IP %s", user["login"], ctx.client_ip(request))
    return JSONResponse({"code": code, "expires_in": accounts.APP_CODE_TTL}, headers={"Cache-Control": "no-store"})


async def app_token(request: Request) -> JSONResponse:
    """The desktop app exchanges the code and its PKCE verifier for a session token."""
    ctx = _ctx(request)
    now = clock.now()
    ip = ctx.client_ip(request)
    if ctx.app_token_limiter.blocked(ip, now):
        raise too_many_attempts()
    data = await json_body(request)
    user_id = accounts.redeem_app_code(ctx.app_codes, data.get("code"), data.get("verifier"), now)
    user = ctx.db.get_user(user_id) if user_id is not None else None
    if user is None:
        ctx.app_token_limiter.hit(ip, now)
        log.warning("failed app connect, IP %s", ip)
        raise ApiError(403, "bad_code", "Unknown, expired or already used code")
    if user["blocked_at"] is not None:
        raise ApiError(403, "blocked", "Account is blocked")
    ctx.app_token_limiter.reset(ip)
    token = accounts.create_session(ctx.db, user["id"], now, ip, request.headers.get("user-agent"))
    ctx.db.update_user(user["id"], last_login_at=now)
    log.info("app connected: %s (%s), IP %s", user["login"], user["email"], ip)
    return JSONResponse({"token": token, "user": session_body(ctx, request, user)},
                        headers={"Cache-Control": "no-store"})


async def logout(request: Request) -> Response:
    ctx = _ctx(request)
    token = ctx.session_token(request)
    if token:
        ctx.db.delete_session(accounts.token_hash(token))
    resp = Response(status_code=204)
    ctx.clear_session_cookie(resp)
    return resp


async def logout_all(request: Request) -> Response:
    ctx = _ctx(request)
    user = ctx.require_user(request)
    accounts.revoke_sessions(ctx.db, user["id"])
    log.info("signed out everywhere: %s", user["login"])
    resp = Response(status_code=204)
    ctx.clear_session_cookie(resp)
    return resp


async def change_password(request: Request) -> Response:
    ctx = _ctx(request)
    user = ctx.require_user(request)
    data = await json_body(request)
    now = clock.now()
    ip = ctx.client_ip(request)
    if ctx.login_limiter.blocked(ip, now):
        raise too_many_attempts()
    if not await _verify(data.get("current"), user["password_hash"]):
        ctx.login_limiter.hit(ip, now)
        raise ApiError(403, "wrong_password", "Current password is wrong")
    new = accounts.check_password(data.get("new"))
    new_hash = await anyio.to_thread.run_sync(auth.hash_password, new)
    ctx.db.update_user(user["id"], password_hash=new_hash)
    # other devices are signed out — in case the password is changed because of a leak
    accounts.revoke_sessions(ctx.db, user["id"], except_token=ctx.session_token(request))
    log.info("password changed: %s", user["login"])
    return Response(status_code=204)


async def token_info(request: Request) -> JSONResponse:
    ctx = _ctx(request)
    row = accounts.peek_token(ctx.db, request.path_params["token"], clock.now())
    reset = row["kind"] == "reset"
    return JSONResponse({
        "kind": row["kind"],
        # an invite has a fixed email; the user picks their username
        "email": row["user_email"] if reset else row["email"],
        "login": row["user_login"] if reset else None,
    }, headers={"Cache-Control": "no-store"})


async def token_accept(request: Request) -> Response:
    ctx = _ctx(request)
    token = request.path_params["token"]
    row = accounts.peek_token(ctx.db, token, clock.now())
    data = await json_body(request)
    if row["kind"] == "invite":
        login = accounts.normalize_login(data.get("login"))
        password = accounts.check_password(data.get("password"))
        pw_hash = await anyio.to_thread.run_sync(auth.hash_password, password)
        result = ctx.db.accept_invite(accounts.token_hash(token), clock.now(), login=login, password_hash=pw_hash)
        if isinstance(result, str):
            raise accounts.token_error(result)
        log.info("signed up by invite: %s (%s), IP %s", login, row["email"], ctx.client_ip(request))
    else:
        password = accounts.check_password(data.get("password"))
        pw_hash = await anyio.to_thread.run_sync(auth.hash_password, password)
        result = ctx.db.accept_reset(accounts.token_hash(token), clock.now(), password_hash=pw_hash)
        if isinstance(result, str):
            raise accounts.token_error(result)
        log.info("password reset by link: %s, IP %s", row["user_login"], ctx.client_ip(request))
    return _login_response(ctx, request, result)
