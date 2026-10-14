"""Serving files: Range/206/416, ETag, If-Range, a safe Content-Disposition.

Multi-gigabyte files are read in 1 MiB chunks in a thread — they never land in memory
whole and do not block the event loop.
"""

from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator
from email.utils import formatdate
from pathlib import Path
from urllib.parse import quote

import anyio
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from share_app.errors import not_found

CHUNK = 1 << 20

# What may be shown inline in the browser. HTML, SVG and other active content is
# download-only, otherwise an uploaded file would execute on our domain.
INLINE_PREFIXES = ("video/", "audio/")
INLINE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/avif", "application/pdf", "text/plain"}

RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def inline_safe(mime: str) -> bool:
    return mime.startswith(INLINE_PREFIXES) or mime in INLINE_TYPES


def content_disposition(disposition: str, filename: str) -> str:
    """RFC 6266/5987: an ASCII fallback name plus `filename*` in UTF-8."""
    fallback = "".join(c if 32 <= ord(c) < 127 and c not in '"\\' else "_" for c in filename) or "file"
    return f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


def parse_range(header: str | None, size: int) -> tuple[int, int] | None | str:
    """(start, end) inclusive; None — no header, or it is unparsable/multi-range
    (then the whole file is sent, which the RFC allows); "unsatisfiable" — 416."""
    if not header:
        return None
    m = RANGE_RE.match(header.strip())
    if not m:
        return None
    first, last = m.group(1), m.group(2)
    if first == "" and last == "":
        return None
    if first == "":
        n = int(last)
        if n == 0 or size == 0:
            return "unsatisfiable"
        return max(0, size - n), size - 1
    start = int(first)
    end = int(last) if last else size - 1
    if last and end < start:
        return None
    if start >= size:
        return "unsatisfiable"
    return start, min(end, size - 1)


async def _iter_file(path: Path, start: int, length: int) -> AsyncIterator[bytes]:
    fh = await anyio.to_thread.run_sync(open, path, "rb")
    try:
        await anyio.to_thread.run_sync(fh.seek, start)
        remaining = length
        while remaining > 0:
            chunk = await anyio.to_thread.run_sync(fh.read, min(CHUNK, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
    finally:
        fh.close()


def serve_file(request: Request, path: Path, *, mime: str, filename: str, download: bool,
               cache_control: str = "private, no-cache") -> Response:
    try:
        st = os.stat(path)
    except FileNotFoundError:
        raise not_found("File not found") from None
    size = st.st_size
    safe = inline_safe(mime)
    ctype = mime if safe else "application/octet-stream"
    if ctype == "text/plain":
        ctype = "text/plain; charset=utf-8"
    etag = f'"{size:x}-{st.st_mtime_ns:x}"'
    last_modified = formatdate(st.st_mtime, usegmt=True)
    headers = {
        "Accept-Ranges": "bytes",
        "ETag": etag,
        "Last-Modified": last_modified,
        "Content-Disposition": content_disposition("inline" if safe and not download else "attachment", filename),
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": cache_control,
        "Content-Type": ctype,
    }

    range_header = request.headers.get("range")
    if_range = request.headers.get("if-range")
    if range_header and if_range and if_range.strip() not in (etag, last_modified):
        range_header = None  # the file changed since last time — send it whole
    if not range_header and request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={k: v for k, v in headers.items() if k != "Content-Type"})

    rng = parse_range(range_header, size)
    if rng == "unsatisfiable":
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"})
    if rng is None:
        status, start, length = 200, 0, size
    else:
        assert isinstance(rng, tuple)
        start, end = rng
        status, length = 206, end - start + 1
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    headers["Content-Length"] = str(length)

    if request.method == "HEAD":
        return Response(status_code=status, headers=headers)
    return StreamingResponse(_iter_file(path, start, length), status_code=status, headers=headers)
