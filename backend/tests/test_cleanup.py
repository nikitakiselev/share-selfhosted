from __future__ import annotations

import os

from starlette.testclient import TestClient

from share_app import accounts
from share_app.cleanup import (
    EXPIRED_GRACE,
    STALE_UPLOAD,
    TOKEN_KEEP,
    remove_orphans,
    run_cleanup,
)
from tests.conftest import new_share, tus_create, tus_patch, upload

DAY = 86400


def test_expired_kept_during_grace_then_removed(admin: TestClient, ctx, fake_clock):
    slug = new_share(admin, expires_at=fake_clock.t + DAY)["slug"]
    fid = upload(admin, slug, b"x", "a.txt")
    fake_clock.advance(DAY + EXPIRED_GRACE - 10)
    run_cleanup(ctx)
    assert ctx.db.get_share(slug) is not None
    fake_clock.advance(20)
    assert run_cleanup(ctx)["expired"] == 1
    assert ctx.db.get_share(slug) is None and not ctx.storage.file_path(fid).exists()


def test_permanent_share_never_expires(admin: TestClient, ctx, fake_clock):
    slug = new_share(admin)["slug"]
    upload(admin, slug, b"x", "a.txt")
    fake_clock.advance(365 * DAY)
    run_cleanup(ctx)
    assert ctx.db.get_share(slug) is not None


def test_stale_upload_removed(admin: TestClient, ctx, fake_clock):
    slug = new_share(admin)["slug"]
    upload(admin, slug, b"keep", "keep.txt")  # so the link does not count as empty
    loc = tus_create(admin, slug, 100).headers["location"]
    tus_patch(admin, loc, b"x" * 10, 0)
    fid = loc.rsplit("/", 1)[1]
    path = ctx.storage.upload_path(fid)
    fake_clock.advance(STALE_UPLOAD + 10)
    # the part's mtime is the "last activity"; move it into the past along with the clock
    os.utime(path, (fake_clock.t - STALE_UPLOAD - 5, fake_clock.t - STALE_UPLOAD - 5))
    assert run_cleanup(ctx)["stale_uploads"] == 1
    assert ctx.db.get_file(fid) is None and not path.exists()
    assert ctx.db.get_share(slug) is not None


def test_active_upload_kept(admin: TestClient, ctx, fake_clock):
    slug = new_share(admin)["slug"]
    loc = tus_create(admin, slug, 100).headers["location"]
    fid = loc.rsplit("/", 1)[1]
    fake_clock.advance(STALE_UPLOAD + 10)
    os.utime(ctx.storage.upload_path(fid), (fake_clock.t - 60, fake_clock.t - 60))
    run_cleanup(ctx)
    assert ctx.db.get_file(fid) is not None


def test_empty_share_removed_after_week(admin: TestClient, ctx, fake_clock):
    slug = new_share(admin)["slug"]
    fake_clock.advance(STALE_UPLOAD - 10)
    run_cleanup(ctx)
    assert ctx.db.get_share(slug) is not None
    fake_clock.advance(20)
    assert run_cleanup(ctx)["empty"] == 1
    assert ctx.db.get_share(slug) is None


def test_orphans_removed(admin: TestClient, ctx):
    slug = new_share(admin)["slug"]
    fid = upload(admin, slug, b"x", "a.txt")
    (ctx.storage.files / "0123456789abcdef").write_bytes(b"orphan")
    (ctx.storage.derived / "fedcba9876543210").mkdir()
    (ctx.storage.uploads / "garbage.tmp").write_bytes(b"")
    assert remove_orphans(ctx) == 3
    assert ctx.storage.file_path(fid).exists()
    assert not (ctx.storage.files / "0123456789abcdef").exists()


def test_sessions_and_tokens_cleaned(user: TestClient, ctx, fake_clock):
    start = fake_clock.t
    old, _ = accounts.create_token(ctx.db, "invite", start)
    fake_clock.advance(accounts.SESSION_TTL - 10)
    assert run_cleanup(ctx)["sessions"] == 0
    fake_clock.advance(20)
    assert run_cleanup(ctx)["sessions"] == 1
    assert ctx.db.user_sessions(user.user_id) == []
    # an expired invite stays for another month — something to look into
    fresh, _ = accounts.create_token(ctx.db, "invite", fake_clock.t)
    fake_clock.t = start + accounts.INVITE_TTL + TOKEN_KEEP - 10
    assert run_cleanup(ctx)["tokens"] == 0
    fake_clock.advance(20)
    assert run_cleanup(ctx)["tokens"] == 1
    assert ctx.db.get_token(accounts.token_hash(old)) is None
    assert ctx.db.get_token(accounts.token_hash(fresh)) is not None
