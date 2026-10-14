"""A user's own links and files and the space they take.

Someone else's link or file answers 404 like a missing one: the response does not reveal that a slug is taken.
"""

from __future__ import annotations

import logging
from typing import Any

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from share_app import auth, clock, quota
from share_app.context import Context, new_slug
from share_app.errors import ApiError, json_body, not_found
from share_app.serialize import admin_file, admin_summary
from share_app.tus import CONTROL_RE, NAME_MAX

log = logging.getLogger("share")

TITLE_MAX = 200
PASSWORD_MAX = 200


def _ctx(request: Request) -> Context:
    return request.app.state.ctx


def _title(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApiError(400, "bad_title", "Title must be a string", max_length=TITLE_MAX)
    value = value.strip()
    if len(value) > TITLE_MAX:
        raise ApiError(400, "bad_title", f"Title is longer than {TITLE_MAX} characters", max_length=TITLE_MAX)
    return value or None


def _name(value: Any) -> str:
    """A file name set by hand. It never reaches a path on disk, but goes into
    Content-Disposition and ZIP — where "/" would turn the name into directories."""
    if not isinstance(value, str):
        raise ApiError(400, "bad_name", "File name must be a string", max_length=NAME_MAX)
    value = CONTROL_RE.sub("", value).replace("/", "_").replace("\\", "_").strip()
    if value in ("", ".", ".."):
        raise ApiError(400, "bad_name", "File name cannot be empty", max_length=NAME_MAX)
    if len(value) > NAME_MAX:
        raise ApiError(400, "bad_name", f"File name is longer than {NAME_MAX} characters", max_length=NAME_MAX)
    return value


def _expires(value: Any, now: int) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(400, "bad_expires", "Expiry must be unix time in seconds or null")
    if value <= now:
        raise ApiError(400, "expires_in_past", "Expiry is in the past")
    return value


def _password(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ApiError(400, "bad_password", "Password must be a non-empty string or null", max_length=PASSWORD_MAX)
    if len(value) > PASSWORD_MAX:
        raise ApiError(400, "bad_password", f"Password is longer than {PASSWORD_MAX} characters",
                       max_length=PASSWORD_MAX)
    return value


def _summary(ctx: Context, slug: str) -> dict[str, Any]:
    row = ctx.db.share_summary(slug)
    if row is None:
        raise not_found("Link not found")
    return admin_summary(row, ctx.share_url(slug), clock.now(), ctx.settings.language)


def _usage(ctx: Context, user: dict[str, Any]) -> dict[str, Any]:
    disk = ctx.storage.disk() if user["role"] == "admin" else None
    return quota.usage(ctx.db, user, disk=disk)


# --- links ---

async def usage(request: Request) -> JSONResponse:
    ctx = _ctx(request)
    user = ctx.require_user(request)
    return JSONResponse(_usage(ctx, user), headers={"Cache-Control": "no-store"})


async def list_shares(request: Request) -> JSONResponse:
    ctx = _ctx(request)
    user = ctx.require_user(request)
    now = clock.now()
    lang = ctx.settings.language
    shares = [admin_summary(r, ctx.share_url(r["slug"]), now, lang) for r in ctx.db.list_shares(user["id"])]
    return JSONResponse({"shares": shares, "usage": _usage(ctx, user)}, headers={"Cache-Control": "no-store"})


async def create_share(request: Request) -> JSONResponse:
    ctx = _ctx(request)
    user = ctx.require_user(request)
    data = await json_body(request)
    now = clock.now()
    title = _title(data.get("title"))
    expires_at = _expires(data.get("expires_at"), now)
    password = _password(data.get("password"))
    pw_hash = await anyio.to_thread.run_sync(auth.hash_password, password) if password else None
    slug = new_slug()
    while ctx.db.get_share(slug) is not None:  # 59 bits — practically never happens
        slug = new_slug()
    ctx.db.create_share(slug, owner_id=user["id"], title=title, expires_at=expires_at, password_hash=pw_hash,
                        created_at=now)
    log.info("link %s created: %s (expires: %s, password: %s)", slug, user["login"], expires_at or "never",
             "yes" if pw_hash else "no")
    return JSONResponse(_summary(ctx, slug), status_code=201)


async def get_share(request: Request) -> JSONResponse:
    ctx = _ctx(request)
    share, _ = ctx.own_share(request, request.path_params["slug"])
    slug = share["slug"]
    body = _summary(ctx, slug)
    files = []
    for f in ctx.db.share_files(slug):
        uploaded = f["size"] if f["status"] == "ready" else (ctx.storage.upload_offset(f["id"]) or 0)
        files.append(admin_file(slug, f, uploaded))
    body["files"] = files
    body["events"] = ctx.db.events(slug, 200)
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


async def patch_share(request: Request) -> JSONResponse:
    ctx = _ctx(request)
    share, _ = ctx.own_share(request, request.path_params["slug"])
    slug = share["slug"]
    data = await json_body(request)
    now = clock.now()
    fields: dict[str, Any] = {}
    if "title" in data:
        fields["title"] = _title(data["title"])
    if "expires_at" in data:
        fields["expires_at"] = _expires(data["expires_at"], now)
    if "password" in data:
        password = _password(data["password"])
        fields["password_hash"] = await anyio.to_thread.run_sync(auth.hash_password, password) if password else None
        # old unlock cookies stop working
        fields["password_version"] = share["password_version"] + 1
    ctx.db.update_share(slug, **fields)
    if fields:
        log.info("link %s changed: %s", slug, ", ".join(k for k in fields if k != "password_version"))
    return JSONResponse(_summary(ctx, slug))


async def delete_share(request: Request) -> Response:
    ctx = _ctx(request)
    share, _ = ctx.own_share(request, request.path_params["slug"])
    slug = share["slug"]
    await anyio.to_thread.run_sync(lambda: ctx.delete_share(slug, reason="manually"))
    return Response(status_code=204)


async def patch_file(request: Request) -> JSONResponse:
    """Rename. The kind and display mode stay from the upload: a video named
    ".txt" still plays in the player."""
    ctx = _ctx(request)
    share, _ = ctx.own_share(request, request.path_params["slug"])
    slug = share["slug"]
    f = ctx.db.get_file(request.path_params["file_id"])
    if f is None or f["share_slug"] != slug:
        raise not_found("File not found")
    data = await json_body(request)
    if "name" in data:
        name = _name(data["name"])
        if name != f["name"]:
            ctx.db.update_file(f["id"], name=name)
            log.info("file %s/%s renamed: %r → %r", slug, f["id"], f["name"], name)
            f = {**f, "name": name}
    uploaded = f["size"] if f["status"] == "ready" else (ctx.storage.upload_offset(f["id"]) or 0)
    return JSONResponse(admin_file(slug, f, uploaded))


async def delete_file(request: Request) -> Response:
    ctx = _ctx(request)
    share, _ = ctx.own_share(request, request.path_params["slug"])
    f = ctx.db.get_file(request.path_params["file_id"])
    if f is None or f["share_slug"] != share["slug"]:
        raise not_found("File not found")
    await anyio.to_thread.run_sync(lambda: ctx.delete_file(f, reason="manually"))
    return Response(status_code=204)
