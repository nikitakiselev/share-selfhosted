from __future__ import annotations

import asyncio
import uuid

import anyio
import pytest
from starlette.testclient import TestClient

from share_app.config import Settings
from tests.conftest import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    TUS,
    new_share,
    tus_create,
    tus_patch,
    upload,
)


def test_options(outsider: TestClient, user: TestClient):
    r = outsider.options("/api/app/tus/")
    assert r.status_code == 204
    assert r.headers["tus-version"] == "1.0.0"
    assert r.headers["tus-extension"] == "creation,termination"
    # disk space is not shown to anonymous users
    assert "tus-max-size" not in r.headers
    # a signed-in user sees no more than their quota leaves
    assert 0 < int(user.options("/api/app/tus/").headers["tus-max-size"]) <= 1 << 30


def test_requires_session(anon: TestClient, admin: TestClient):
    slug = new_share(admin)["slug"]
    assert tus_create(anon, slug, 10).status_code == 401


def test_full_upload(admin: TestClient, ctx):
    slug = new_share(admin)["slug"]
    data = b"hello world" * 1000
    r = tus_create(admin, slug, len(data), "привет.txt", "text/plain", lastmodified="1700000000000")
    assert r.status_code == 201
    loc = r.headers["location"]
    assert loc.startswith("/api/app/tus/")
    fid = loc.rsplit("/", 1)[1]
    # on disk the file is stored under a UUID7, the original name is only in the DB
    assert uuid.UUID(fid).version == 7 and str(uuid.UUID(fid)) == fid
    assert ctx.storage.upload_path(fid).name == fid
    assert admin.head(loc, headers=TUS).headers["upload-offset"] == "0"

    r = tus_patch(admin, loc, data[:5000], 0)
    assert r.status_code == 204 and r.headers["upload-offset"] == "5000"
    h = admin.head(loc, headers=TUS)
    assert h.headers["upload-offset"] == "5000" and h.headers["upload-length"] == str(len(data))
    assert h.headers["cache-control"] == "no-store"

    r = tus_patch(admin, loc, data[5000:], 5000)
    assert r.status_code == 204 and r.headers["upload-offset"] == str(len(data))

    f = ctx.db.get_file(fid)
    assert f["status"] == "ready" and f["name"] == "привет.txt" and f["last_modified"] == 1700000000000
    assert ctx.storage.file_path(fid).read_bytes() == data
    assert not ctx.storage.upload_path(fid).exists()
    # a repeated PATCH to a finished upload with the right offset is a harmless 204
    assert tus_patch(admin, loc, b"", len(data)).status_code == 204


def test_offset_mismatch(admin: TestClient):
    slug = new_share(admin)["slug"]
    loc = tus_create(admin, slug, 100).headers["location"]
    tus_patch(admin, loc, b"x" * 10, 0)
    r = tus_patch(admin, loc, b"x" * 10, 0)
    assert r.status_code == 409 and r.headers["upload-offset"] == "10"


def test_bad_requests(admin: TestClient):
    slug = new_share(admin)["slug"]
    loc = tus_create(admin, slug, 100).headers["location"]
    r = admin.patch(loc, content=b"x", headers={**TUS, "Upload-Offset": "0", "Content-Type": "text/plain"})
    assert r.status_code == 415
    r = admin.patch(loc, content=b"x", headers={"Upload-Offset": "0", "Content-Type": "application/offset+octet-stream"})
    assert r.status_code == 412
    assert tus_create(admin, "nonexistent", 10).status_code == 404
    r = admin.post("/api/app/tus/", headers={**TUS, "Upload-Defer-Length": "1"})
    assert r.status_code == 400


def test_overflow_rejected(admin: TestClient, ctx):
    slug = new_share(admin)["slug"]
    loc = tus_create(admin, slug, 4).headers["location"]
    r = tus_patch(admin, loc, b"12345678", 0)
    assert r.status_code == 400 and r.headers["upload-offset"] == "4"
    fid = loc.rsplit("/", 1)[1]
    assert ctx.storage.file_path(fid).read_bytes() == b"1234"


def test_zero_length(admin: TestClient, ctx):
    slug = new_share(admin)["slug"]
    fid = upload(admin, slug, b"", "empty.txt")
    assert ctx.db.get_file(fid)["status"] == "ready"
    assert ctx.storage.file_path(fid).read_bytes() == b""


def test_delete_upload(admin: TestClient, ctx):
    slug = new_share(admin)["slug"]
    loc = tus_create(admin, slug, 100).headers["location"]
    fid = loc.rsplit("/", 1)[1]
    tus_patch(admin, loc, b"x" * 10, 0)
    assert admin.delete(loc, headers=TUS).status_code == 204
    assert ctx.db.get_file(fid) is None
    assert not ctx.storage.upload_path(fid).exists()
    assert admin.head(loc, headers=TUS).status_code == 404


def test_no_space(make_client, settings: Settings, tmp_path):
    from dataclasses import replace

    from share_app.app import create_app

    app = create_app(replace(settings, data_dir=tmp_path / "d2", disk_reserve=10**18))
    with TestClient(app, base_url="https://share.test", client=("192.168.1.10", 1),
                    headers={"Origin": "https://share.test"}) as c:
        c.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        slug = new_share(c)["slug"]
        r = tus_create(c, slug, 10)
        assert r.status_code == 413
        assert r.json()["error"] == "no_space" and r.json()["needed"] == 10 and r.json()["free"] == 0


def test_capacity_counts_pending_uploads(admin: TestClient, ctx):
    slug = new_share(admin)["slug"]
    before = ctx.upload_capacity()
    tus_create(admin, slug, 10_000_000)
    after = ctx.upload_capacity()
    # free disk space may drift a little — compare with a margin
    assert before - after >= 10_000_000 - 1_000_000


def test_concurrent_patch_locked(admin: TestClient, ctx):
    slug = new_share(admin)["slug"]
    loc = tus_create(admin, slug, 100).headers["location"]
    fid = loc.rsplit("/", 1)[1]
    lock = asyncio.Lock()
    ctx.upload_locks[fid] = lock

    async def hold():
        await lock.acquire()

    anyio.run(hold)
    r = tus_patch(admin, loc, b"x", 0)
    assert r.status_code == 423


def test_disconnect_keeps_written_bytes_and_resumes(app, ctx, admin: TestClient):
    """A drop in the middle of the body: what was written stays, resuming continues from there."""
    slug = new_share(admin)["slug"]
    loc = tus_create(admin, slug, 3000).headers["location"]
    fid = loc.rsplit("/", 1)[1]
    token = admin.cookies.get("share_session")

    async def broken_patch():
        messages = [
            {"type": "http.request", "body": b"a" * 1000, "more_body": True},
            {"type": "http.request", "body": b"b" * 500, "more_body": True},
            {"type": "http.disconnect"},
        ]

        async def receive():
            if messages:
                return messages.pop(0)
            await anyio.sleep_forever()

        async def send(message):
            pass

        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "PATCH",
            "scheme": "https", "path": loc, "raw_path": loc.encode(), "query_string": b"", "root_path": "",
            "headers": [
                (b"host", b"share.test"), (b"tus-resumable", b"1.0.0"), (b"upload-offset", b"0"),
                (b"content-type", b"application/offset+octet-stream"),
                (b"cookie", f"share_session={token}".encode()), (b"origin", b"https://share.test"),
            ],
            "client": ("192.168.1.10", 1), "server": ("share.test", 443),
        }
        await app(scope, receive, send)

    anyio.run(broken_patch)
    assert ctx.storage.upload_offset(fid) == 1500
    assert fid not in ctx.upload_locks  # the lock is released
    h = admin.head(loc, headers=TUS)
    assert h.headers["upload-offset"] == "1500"
    r = tus_patch(admin, loc, b"c" * 1500, 1500)
    assert r.status_code == 204
    assert ctx.storage.file_path(fid).read_bytes() == b"a" * 1000 + b"b" * 500 + b"c" * 1500


@pytest.mark.parametrize("raw,expected", [
    ("../../etc/passwd", "passwd"),
    ("C:\\Users\\me\\видео.mp4", "видео.mp4"),
    ("..", "file"),
    ("a\x00b\x1fc.txt", "abc.txt"),
])
def test_filename_sanitized(raw, expected):
    from share_app.tus import sanitize_filename

    assert sanitize_filename(raw) == expected


def test_long_filename_keeps_extension():
    from share_app.tus import sanitize_filename

    name = sanitize_filename("я" * 300 + ".mkv")
    assert len(name) == 255 and name.endswith(".mkv")


def test_file_ids_are_uuid7_ordered_by_time(monkeypatch):
    from share_app import context

    monkeypatch.setattr(context.time, "time_ns", lambda: 1_700_000_000_000 * 1_000_000)
    early = context.new_file_id()
    monkeypatch.setattr(context.time, "time_ns", lambda: 1_700_000_000_001 * 1_000_000)
    late = context.new_file_id()
    assert uuid.UUID(early).int >> 80 == 1_700_000_000_000
    assert early < late
    assert uuid.UUID(late).variant == uuid.RFC_4122

