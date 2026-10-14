"""tus 1.0.0 (core + creation + termination) for resumable uploads.

The upload offset is the size of `uploads/<id>` on disk and is not stored separately:
after a process crash or a dropped connection it always matches what was actually written.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import os
import re
from typing import Any

import anyio
from starlette.requests import ClientDisconnect, Request
from starlette.responses import Response

from share_app import clock
from share_app.context import Context, new_file_id
from share_app.errors import ApiError
from share_app.fmt import human_size
from share_app.media import MEDIA_KINDS, guess_mime, kind_of
from share_app.storage import FILE_ID_RE

log = logging.getLogger("share")

TUS_VERSION = "1.0.0"
CHUNK = 1 << 20
NAME_MAX = 255
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _ctx(request: Request) -> Context:
    return request.app.state.ctx


def _response(status: int, headers: dict[str, str] | None = None) -> Response:
    return Response(status_code=status, headers={"Tus-Resumable": TUS_VERSION, "Cache-Control": "no-store",
                                                 **(headers or {})})


def _check_version(request: Request) -> None:
    if request.headers.get("tus-resumable") != TUS_VERSION:
        raise ApiError(412, "tus_version", "tus protocol 1.0.0 required", headers={"Tus-Version": TUS_VERSION})


def parse_metadata(raw: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not raw:
        return out
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        key, _, value = pair.partition(" ")
        try:
            out[key] = base64.b64decode(value.strip(), validate=True).decode("utf-8") if value.strip() else ""
        except (binascii.Error, UnicodeDecodeError):
            raise ApiError(400, "bad_metadata", f"Upload-Metadata: value of {key!r} is not base64") from None
    return out


def sanitize_filename(name: str) -> str:
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = CONTROL_RE.sub("", name).strip()
    if name in ("", ".", ".."):
        return "file"
    if len(name) > NAME_MAX:
        stem, dot, ext = name.rpartition(".")
        if dot and 0 < len(ext) <= 16:
            name = stem[: NAME_MAX - len(ext) - 1] + "." + ext
        else:
            name = name[:NAME_MAX]
    return name


async def options(request: Request) -> Response:
    ctx = _ctx(request)
    headers = {"Tus-Version": TUS_VERSION, "Tus-Extension": "creation,termination"}
    user = ctx.current_user(request)
    # free disk space only for signed-in users: OPTIONS is open to the internet
    if user is not None:
        capacity = await anyio.to_thread.run_sync(ctx.upload_capacity)
        quota = user["quota_bytes"]
        if quota is not None:
            capacity = min(capacity, max(0, quota - ctx.db.used_bytes(user["id"])))
        headers["Tus-Max-Size"] = str(capacity)
    return _response(204, headers)


async def create(request: Request) -> Response:
    ctx = _ctx(request)
    user = ctx.require_user(request)
    _check_version(request)
    raw_length = request.headers.get("upload-length", "")
    if not raw_length.isdigit():
        raise ApiError(400, "bad_length", "Upload-Length header required (deferred length is not supported)")
    length = int(raw_length)
    meta = parse_metadata(request.headers.get("upload-metadata"))
    slug = meta.get("share", "")
    ctx.own_share(request, slug)
    capacity = await anyio.to_thread.run_sync(ctx.upload_capacity)
    if length > capacity:
        raise ApiError(413, "no_space",
                       f"Not enough disk space: need {human_size(length)}, free {human_size(capacity)}",
                       needed=length, free=capacity)
    # The quota is checked only here: a started upload completes even if the quota was lowered since.
    # There is no await between the check and add_file — two parallel uploads cannot both slip through.
    quota = user["quota_bytes"]
    if quota is not None:
        free = max(0, quota - ctx.db.used_bytes(user["id"]))
        if length > free:
            raise ApiError(413, "quota_exceeded",
                           f"Quota exceeded: need {human_size(length)}, free {human_size(free)}",
                           needed=length, free=free)
    name = sanitize_filename(meta.get("filename") or "file")
    mime = guess_mime(name, meta.get("filetype"))
    lm = meta.get("lastmodified", "")
    file_id = new_file_id()
    ctx.storage.upload_path(file_id).touch(exist_ok=False)
    ctx.db.add_file(file_id=file_id, share_slug=slug, name=name, size=length, mime=mime, kind=kind_of(mime),
                    created_at=clock.now(), last_modified=int(lm) if lm.isdigit() else None)
    if length == 0:
        await finalize(ctx, file_id)
    return _response(201, {"Location": f"/api/app/tus/{file_id}", "Upload-Offset": "0"})


def _get_file(ctx: Context, request: Request, user: dict[str, Any]) -> dict[str, Any]:
    """A file from the user's own link; someone else's answers like a missing one."""
    file_id = request.path_params["file_id"]
    f = ctx.db.get_file(file_id) if FILE_ID_RE.match(file_id) else None
    share = ctx.db.get_share(f["share_slug"]) if f is not None else None
    if f is None or share is None or share["owner_id"] != user["id"]:
        raise ApiError(404, "not_found", "Upload not found", headers={"Tus-Resumable": TUS_VERSION})
    return f


def _offset(ctx: Context, f: dict[str, Any]) -> int:
    if f["status"] == "ready":
        return f["size"]
    offset = ctx.storage.upload_offset(f["id"])
    if offset is None:
        raise ApiError(404, "not_found", "Upload not found", headers={"Tus-Resumable": TUS_VERSION})
    return offset


async def resource(request: Request) -> Response:
    if request.method == "OPTIONS":
        return await options(request)
    ctx = _ctx(request)
    user = ctx.require_user(request)
    _check_version(request)
    f = _get_file(ctx, request, user)
    if request.method == "HEAD":
        return _response(200, {"Upload-Offset": str(_offset(ctx, f)), "Upload-Length": str(f["size"])})
    if request.method == "DELETE":
        await anyio.to_thread.run_sync(lambda: ctx.delete_file(f, reason="upload cancelled"))
        return _response(204)
    return await _patch(ctx, request, f)


async def _patch(ctx: Context, request: Request, f: dict[str, Any]) -> Response:
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/offset+octet-stream":
        raise ApiError(415, "bad_content_type", "Content-Type: application/offset+octet-stream required")
    raw_offset = request.headers.get("upload-offset", "")
    if not raw_offset.isdigit():
        raise ApiError(400, "bad_offset", "Upload-Offset header required")
    client_offset = int(raw_offset)
    file_id = f["id"]

    if f["status"] == "ready":
        if client_offset == f["size"]:
            return _response(204, {"Upload-Offset": str(f["size"])})
        raise ApiError(409, "offset_mismatch", "Upload already complete", headers={"Upload-Offset": str(f["size"])})

    lock = ctx.upload_locks.setdefault(file_id, asyncio.Lock())
    if lock.locked():
        raise ApiError(423, "locked", "This file is being uploaded by another request")
    async with lock:
        try:
            return await _write(ctx, request, f, client_offset)
        finally:
            ctx.upload_locks.pop(file_id, None)


async def _write(ctx: Context, request: Request, f: dict[str, Any], client_offset: int) -> Response:
    file_id = f["id"]
    path = ctx.storage.upload_path(file_id)
    current = _offset(ctx, f)
    if client_offset != current:
        raise ApiError(409, "offset_mismatch", "Offset does not match the server",
                       headers={"Upload-Offset": str(current), "Tus-Resumable": TUS_VERSION})
    remaining = f["size"] - current
    fh = await anyio.to_thread.run_sync(open, path, "ab")
    buf = bytearray()
    written = 0
    overflow = False

    def flush_close(data: bytes) -> None:
        try:
            if data:
                fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        finally:
            fh.close()

    try:
        async for chunk in request.stream():
            if not chunk:
                continue
            room = remaining - written - len(buf)
            if len(chunk) > room:
                chunk, overflow = chunk[:room], True
            buf += chunk
            if len(buf) >= CHUNK:
                data, buf = bytes(buf), bytearray()
                await anyio.to_thread.run_sync(fh.write, data)
                written += len(data)
            if overflow:
                break
    except ClientDisconnect:
        pass  # what was written stays — the client resumes from here
    finally:
        tail, buf = bytes(buf), bytearray()
        with anyio.CancelScope(shield=True):
            await anyio.to_thread.run_sync(flush_close, tail)
        written += len(tail)

    offset = current + written
    if offset == f["size"]:
        await finalize(ctx, file_id)
    if overflow:
        raise ApiError(400, "too_much_data", "More data than Upload-Length",
                       headers={"Upload-Offset": str(offset), "Tus-Resumable": TUS_VERSION})
    return _response(204, {"Upload-Offset": str(offset)})


async def finalize(ctx: Context, file_id: str) -> None:
    """The last byte arrived: move to files/ and queue for processing."""
    f = ctx.db.get_file(file_id)
    if f is None:
        return
    try:
        await anyio.to_thread.run_sync(os.replace, ctx.storage.upload_path(file_id), ctx.storage.file_path(file_id))
    except FileNotFoundError:
        return  # deleted while the upload was finishing
    if ctx.db.get_file(file_id) is None:
        ctx.storage.remove(file_id)
        return
    media = f["kind"] in MEDIA_KINDS
    ctx.db.update_file(file_id, status="ready", completed_at=clock.now(), media_status="pending" if media else "none")
    log.info("upload complete: %s/%s %r, %s", f["share_slug"], file_id, f["name"], human_size(f["size"]))
    if media:
        ctx.worker.enqueue()
