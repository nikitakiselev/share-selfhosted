"""Cleanup: expired links, abandoned uploads, empty links, sessions and tokens, orphans on disk."""

from __future__ import annotations

import asyncio
import logging
import shutil

import anyio

from share_app import clock
from share_app.context import Context

log = logging.getLogger("share")

# window after expiry during which a link can still be extended
EXPIRED_GRACE = 7 * 86400
# an upload idle for longer than this is abandoned
STALE_UPLOAD = 7 * 86400
EMPTY_SHARE = 7 * 86400
# used and expired invites stay in the DB for a month — so there is something to investigate
TOKEN_KEEP = 30 * 86400


def run_cleanup(ctx: Context) -> dict[str, int]:
    now = clock.now()
    counts = {"expired": 0, "stale_uploads": 0, "empty": 0, "sessions": 0, "tokens": 0}
    for slug in ctx.db.shares_expired_before(now - EXPIRED_GRACE):
        if ctx.delete_share(slug, reason="expired"):
            counts["expired"] += 1
    for f in ctx.db.uploading_files():
        if f["id"] in ctx.upload_locks:  # being written right now
            continue
        try:
            last = int(ctx.storage.upload_path(f["id"]).stat().st_mtime)
        except FileNotFoundError:
            last = f["created_at"]
        if last <= now - STALE_UPLOAD:
            ctx.delete_file(f, reason="upload abandoned")
            counts["stale_uploads"] += 1
    for slug in ctx.db.empty_shares_created_before(now - EMPTY_SHARE):
        if ctx.delete_share(slug, reason="empty"):
            counts["empty"] += 1
    counts["sessions"] = ctx.db.delete_expired_sessions(now)
    counts["tokens"] = ctx.db.delete_tokens_expired_before(now - TOKEN_KEEP)
    return counts


def remove_orphans(ctx: Context) -> int:
    """On start: everything on disk the DB does not know about — leftovers of interrupted operations."""
    known = ctx.db.all_file_ids()
    removed = 0
    for fid in ctx.storage.ids_on_disk() - known:
        ctx.storage.remove(fid)
        removed += 1
    for path in ctx.storage.stray_entries():
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
        removed += 1
    if removed:
        log.info("removed orphans on disk: %d", removed)
    return removed


async def loop(ctx: Context) -> None:
    while True:
        try:
            counts = await anyio.to_thread.run_sync(run_cleanup, ctx)
            if any(counts.values()):
                log.info("cleanup: expired %(expired)d, abandoned uploads %(stale_uploads)d, empty %(empty)d, "
                         "sessions %(sessions)d, tokens %(tokens)d", counts)
        except Exception:  # cleanup must not die for good
            log.exception("cleanup failed")
        await asyncio.sleep(ctx.settings.cleanup_interval)
