"""User and invite management.

Admin role only and internal networks only: the path is cut by AccessMiddleware, and every
handler checks again via `require_admin_panel`.
"""

from __future__ import annotations

import logging
from typing import Any

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from share_app import accounts, clock
from share_app.context import Context
from share_app.errors import ApiError, json_body, not_found
from share_app.fmt import human_size

log = logging.getLogger("share")


def _ctx(request: Request) -> Context:
    return request.app.state.ctx


def admin_user(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "login": row["login"],
        "email": row["email"],
        "role": row["role"],
        "quota": row["quota_bytes"],
        "used": row["used"],
        "share_count": row["share_count"],
        "created_at": row["created_at"],
        "last_login_at": row["last_login_at"],
        "blocked": row["blocked_at"] is not None,
    }


def _target(ctx: Context, request: Request) -> dict[str, Any]:
    row = ctx.db.user_with_usage(request.path_params["user_id"])
    if row is None:
        raise not_found("User not found")
    return row


def _quota(value: Any) -> int | None:
    """Quota in bytes from the request body: an integer above zero, or null — unlimited."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ApiError(400, "bad_quota", "Quota must be a positive number of bytes or null (unlimited)")
    return value


def _quota_title(quota: int | None) -> str:
    return "unlimited" if quota is None else human_size(quota)


def _invite(row: dict[str, Any], url: str | None = None) -> dict[str, Any]:
    body = {
        "id": row["id"],
        "email": row["email"],
        "quota": row["quota_bytes"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
    }
    if url is not None:
        body["url"] = url
    return body


# --- users ---

async def list_users(request: Request) -> JSONResponse:
    ctx = _ctx(request)
    ctx.require_admin_panel(request)
    rows = ctx.db.list_users()
    disk = await anyio.to_thread.run_sync(ctx.storage.disk)
    return JSONResponse({
        "users": [admin_user(r) for r in rows],
        "disk": {"used": disk.used, "total": disk.total, "free": disk.free},
        # total promised by quotas — may exceed the disk, a deliberate oversell
        "allocated": sum(r["quota_bytes"] for r in rows if r["quota_bytes"] is not None),
        "default_quota": ctx.settings.default_quota,
    }, headers={"Cache-Control": "no-store"})


async def patch_user(request: Request) -> JSONResponse:
    ctx = _ctx(request)
    me = ctx.require_admin_panel(request)
    target = _target(ctx, request)
    data = await json_body(request)
    now = clock.now()
    if target["role"] == "admin" and "blocked" in data:
        raise ApiError(400, "bad_request", "An admin cannot be blocked")

    # validate everything before the first write: an error in one field must not apply the others
    set_quota = "quota" in data
    quota = _quota(data["quota"]) if set_quota else None
    blocked: bool | None = None
    if "blocked" in data:
        if not isinstance(data["blocked"], bool):
            raise ApiError(400, "bad_request", "blocked must be true or false")
        blocked = data["blocked"]

    if set_quota and quota != target["quota_bytes"]:
        ctx.db.update_user(target["id"], quota_bytes=quota)
        log.info("quota of %s: %s (by %s)", target["login"], _quota_title(quota), me["login"])
    if blocked is True and target["blocked_at"] is None:
        ctx.db.update_user(target["id"], blocked_at=now)
        accounts.revoke_sessions(ctx.db, target["id"])
        log.warning("user %s blocked (by %s)", target["login"], me["login"])
    elif blocked is False and target["blocked_at"] is not None:
        ctx.db.update_user(target["id"], blocked_at=None)
        log.info("user %s unblocked (by %s)", target["login"], me["login"])
    return JSONResponse(admin_user(_target(ctx, request)))


async def delete_user(request: Request) -> Response:
    ctx = _ctx(request)
    me = ctx.require_admin_panel(request)
    target = _target(ctx, request)
    if target["role"] == "admin":
        raise ApiError(400, "bad_request", "An admin cannot be deleted")
    await anyio.to_thread.run_sync(lambda: ctx.delete_user(target, reason=f"by {me['login']}"))
    return Response(status_code=204)


async def reset_link(request: Request) -> JSONResponse:
    ctx = _ctx(request)
    me = ctx.require_admin_panel(request)
    target = _target(ctx, request)
    token, row = accounts.create_token(ctx.db, "reset", clock.now(), user_id=target["id"])
    log.info("password reset link issued for %s (by %s)", target["login"], me["login"])
    return JSONResponse({"url": f"{ctx.settings.public_url}/reset/{token}", "expires_at": row["expires_at"]},
                        headers={"Cache-Control": "no-store"})


# --- invites ---

async def list_invites(request: Request) -> JSONResponse:
    ctx = _ctx(request)
    ctx.require_admin_panel(request)
    rows = ctx.db.active_invites(clock.now())
    return JSONResponse({"invites": [_invite(r) for r in rows]}, headers={"Cache-Control": "no-store"})


def _invite_response(ctx: Context, invite_id: int, token: str, status_code: int) -> JSONResponse:
    row = ctx.db.get_token_by_id(invite_id)
    assert row is not None
    return JSONResponse(_invite(row, f"{ctx.settings.public_url}/invite/{token}"), status_code=status_code,
                        headers={"Cache-Control": "no-store"})


async def create_invite(request: Request) -> JSONResponse:
    """An invite to an email. An unused earlier invite to the same address is replaced."""
    ctx = _ctx(request)
    me = ctx.require_admin_panel(request)
    data = await json_body(request)
    email = accounts.normalize_email(data.get("email"))
    quota = _quota(data["quota"]) if "quota" in data else ctx.settings.default_quota
    now = clock.now()
    token = accounts.new_token()
    result = ctx.db.replace_invite(accounts.token_hash(token), email=email, quota_bytes=quota,
                                   now=now, expires_at=now + accounts.INVITE_TTL)
    if isinstance(result, str):
        raise accounts.token_error(result)
    log.info("invite %d created: %s, quota %s (by %s)", result, email, _quota_title(quota), me["login"])
    return _invite_response(ctx, result, token, 201)


async def renew_invite(request: Request) -> JSONResponse:
    """A new link instead of a lost one: the original token is not stored, so it cannot be shown again."""
    ctx = _ctx(request)
    me = ctx.require_admin_panel(request)
    invite_id = request.path_params["invite_id"]
    token = accounts.new_token()
    error = ctx.db.renew_invite(invite_id, accounts.token_hash(token), expires_at=clock.now() + accounts.INVITE_TTL)
    if error == "not_found":
        raise not_found("Invite not found")
    if error is not None:
        raise accounts.token_error(error)
    row = ctx.db.get_token_by_id(invite_id)
    log.info("invite %d: new link (%s) (by %s)", invite_id, row["email"] if row else "?", me["login"])
    return _invite_response(ctx, invite_id, token, 200)


async def delete_invite(request: Request) -> Response:
    ctx = _ctx(request)
    me = ctx.require_admin_panel(request)
    invite_id = request.path_params["invite_id"]
    if not ctx.db.delete_invite(invite_id):
        raise not_found("Invite not found")
    log.info("invite %d revoked (by %s)", invite_id, me["login"])
    return Response(status_code=204)
