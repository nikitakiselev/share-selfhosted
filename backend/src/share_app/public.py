"""Public API: link card, password, files, player, poster, ZIP.

Open to anyone who has the link. The owner (by session) sees their link after expiry
and without the password; links of a blocked owner do not open at all.
"""

from __future__ import annotations

import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from share_app import auth, clock, stats
from share_app.context import Context
from share_app.errors import ApiError, not_found, too_many_attempts
from share_app.files import content_disposition, serve_file
from share_app.serialize import display_title, is_expired, public_file
from share_app.zipper import build_zip, stream_zip, unique_names


def _ctx(request: Request) -> Context:
    return request.app.state.ctx


def _get_share(ctx: Context, slug: str) -> dict[str, Any]:
    share = ctx.db.get_share(slug)
    if share is None or share["owner_blocked_at"] is not None:
        raise not_found("Link not found")
    return share


def _expired_error(share: dict[str, Any]) -> ApiError:
    return ApiError(410, "expired", "The link has expired", expired_at=share["expires_at"])


def _unlocked(ctx: Context, request: Request, share: dict[str, Any]) -> bool:
    if share["password_hash"] is None:
        return True
    token = request.cookies.get(auth.unlock_cookie_name(share["slug"]))
    return auth.check_unlock_token(ctx.settings.secret, token, share["slug"], share["password_version"], clock.now())


def _access(ctx: Context, request: Request) -> dict[str, Any]:
    """A link whose content may be accessed: it exists, has not expired, is unlocked.
    The owner bypasses expiry and password."""
    share = _get_share(ctx, request.path_params["slug"])
    if ctx.is_owner(request, share):
        return share
    if is_expired(share, clock.now()):
        raise _expired_error(share)
    if not _unlocked(ctx, request, share):
        raise ApiError(401, "locked", "The link is password-protected")
    return share


def _file(ctx: Context, request: Request, share: dict[str, Any]) -> dict[str, Any]:
    f = ctx.db.get_file(request.path_params["file_id"])
    if f is None or f["share_slug"] != share["slug"]:
        raise not_found("File not found")
    return f


async def share_card(request: Request) -> JSONResponse:
    ctx = _ctx(request)
    share = _get_share(ctx, request.path_params["slug"])
    now = clock.now()
    owner = ctx.is_owner(request, share)
    if is_expired(share, now) and not owner:
        raise _expired_error(share)
    protected = share["password_hash"] is not None
    unlocked = owner or _unlocked(ctx, request, share)
    stats.record(ctx, request, share, "view")
    body: dict[str, Any] = {
        "slug": share["slug"],
        "title": None,
        "created_at": share["created_at"],
        "expires_at": share["expires_at"],
        "protected": protected,
        "unlocked": unlocked,
        "total_size": None,
        "file_count": None,
        "files": [],
    }
    if unlocked:
        files = ctx.db.ready_files(share["slug"])
        body["title"] = display_title(share, files[0]["name"] if files else None, ctx.settings.language)
        body["total_size"] = sum(f["size"] for f in files)
        body["file_count"] = len(files)
        body["files"] = [public_file(share["slug"], f) for f in files]
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


async def unlock(request: Request) -> Response:
    ctx = _ctx(request)
    share = _get_share(ctx, request.path_params["slug"])
    now = clock.now()
    if is_expired(share, now):
        raise _expired_error(share)
    if share["password_hash"] is None:
        return Response(status_code=204)
    key = f"{ctx.client_ip(request)}|{share['slug']}"
    if ctx.unlock_limiter.blocked(key, now):
        raise too_many_attempts()
    try:
        data = await request.json()
    except ValueError:
        raise ApiError(400, "bad_json", "Expected JSON") from None
    password = data.get("password") if isinstance(data, dict) else None
    if not isinstance(password, str) or not auth.verify_password(password, share["password_hash"]):
        ctx.unlock_limiter.hit(key, now)
        raise ApiError(403, "wrong_password", "Wrong password")
    ctx.unlock_limiter.reset(key)
    token = auth.make_unlock_token(ctx.settings.secret, share["slug"], share["password_version"], now)
    resp = Response(status_code=204)
    resp.set_cookie(
        auth.unlock_cookie_name(share["slug"]), token, max_age=auth.UNLOCK_TTL, path="/",
        httponly=True, secure=ctx.settings.cookie_secure, samesite="lax",
    )
    return resp


async def file_original(request: Request) -> Response:
    ctx = _ctx(request)
    share = _access(ctx, request)
    f = _file(ctx, request, share)
    if f["status"] != "ready":
        raise not_found("The file is still uploading")
    download = request.query_params.get("download") == "1"
    if download and request.method == "GET":
        rng = (request.headers.get("range") or "").replace(" ", "")
        if not rng or rng.startswith("bytes=0-"):
            stats.record(ctx, request, share, "download", f["id"])
    return serve_file(request, ctx.storage.file_path(f["id"]), mime=f["mime"], filename=f["name"], download=download)


async def file_play(request: Request) -> Response:
    ctx = _ctx(request)
    share = _access(ctx, request)
    f = _file(ctx, request, share)
    if f["status"] != "ready" or f["media_status"] != "done" or f["play"] == "none":
        raise not_found("Playback is not available")
    if f["play"] == "remux":
        path, mime = ctx.storage.play_path(f["id"]), "video/mp4"
        name = re.sub(r"\.[^.]*$", "", f["name"]) + ".mp4"
    else:
        path, name = ctx.storage.file_path(f["id"]), f["name"]
        if f["kind"] == "video":
            # MOV and M4V are the same MP4 family; browsers accept them more readily as video/mp4
            mime = "video/webm" if f["name"].lower().endswith(".webm") else "video/mp4"
        else:
            mime = f["mime"]
    return serve_file(request, path, mime=mime, filename=name, download=False)


async def file_poster(request: Request) -> Response:
    ctx = _ctx(request)
    share = _access(ctx, request)
    f = _file(ctx, request, share)
    if not f["has_poster"]:
        raise not_found("No preview")
    return serve_file(request, ctx.storage.poster_path(f["id"]), mime="image/jpeg", filename="poster.jpg",
                      download=False)


async def file_played(request: Request) -> Response:
    ctx = _ctx(request)
    share = _access(ctx, request)
    f = _file(ctx, request, share)
    stats.record(ctx, request, share, "play", f["id"])
    return Response(status_code=204)


ZIP_BAD_CHARS = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]+')


async def share_zip(request: Request) -> Response:
    ctx = _ctx(request)
    share = _access(ctx, request)
    files = ctx.db.ready_files(share["slug"])
    if not files:
        raise not_found("No ready files")
    names = unique_names(f["name"] for f in files)
    zs = build_zip((ctx.storage.file_path(f["id"]), n) for f, n in zip(files, names, strict=True))
    title = ZIP_BAD_CHARS.sub("_", display_title(share, files[0]["name"])).strip(" .")[:150] or share["slug"]
    headers = {
        "Content-Length": str(len(zs)),
        "Content-Disposition": content_disposition("attachment", f"{title}.zip"),
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
    }
    if request.method == "HEAD":
        return Response(headers=headers, media_type="application/zip")
    stats.record(ctx, request, share, "zip")
    return StreamingResponse(stream_zip(zs), media_type="application/zip", headers=headers)
