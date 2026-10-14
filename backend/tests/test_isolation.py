from __future__ import annotations

from starlette.testclient import TestClient

from tests.conftest import TUS, new_share, tus_create, tus_patch, upload


def test_other_user_gets_404_everywhere(user: TestClient, other_user: TestClient, admin: TestClient, ctx):
    slug = new_share(user, title="A", password="secret")["slug"]
    fid = upload(user, slug, b"hello", "a.txt")
    loc = tus_create(user, slug, 100).headers["location"]
    assert tus_patch(user, loc, b"x" * 10, 0).status_code == 204
    pending = loc.rsplit("/", 1)[1]
    before = user.get(f"/api/app/shares/{slug}").json()

    b = other_user
    own = new_share(b)["slug"]
    attempts = {
        "get share": b.get(f"/api/app/shares/{slug}"),
        "patch share": b.patch(f"/api/app/shares/{slug}", json={"title": "pwned", "password": None}),
        "rename file": b.patch(f"/api/app/shares/{slug}/files/{fid}", json={"name": "x.txt"}),
        "delete file": b.delete(f"/api/app/shares/{slug}/files/{fid}"),
        # someone else's file through one's own link
        "rename via own": b.patch(f"/api/app/shares/{own}/files/{fid}", json={"name": "x.txt"}),
        "delete via own": b.delete(f"/api/app/shares/{own}/files/{fid}"),
        "delete share": b.delete(f"/api/app/shares/{slug}"),
        "tus create": tus_create(b, slug, 10),
        "tus head": b.head(loc, headers=TUS),
        "tus patch": tus_patch(b, loc, b"y" * 10, 10),
        "tus delete": b.delete(loc, headers=TUS),
        "tus delete ready": b.delete(f"/api/app/tus/{fid}", headers=TUS),
        # an admin in /api/app is a regular user and sees nothing of others
        "admin get": admin.get(f"/api/app/shares/{slug}"),
    }
    for name, r in attempts.items():
        assert r.status_code == 404, name
        if r.request.method != "HEAD":
            assert r.json()["error"] == "not_found", name

    assert [s["slug"] for s in b.get("/api/app/shares").json()["shares"]] == [own]
    assert slug not in [s["slug"] for s in admin.get("/api/app/shares").json()["shares"]]
    # nothing changed for A
    assert user.get(f"/api/app/shares/{slug}").json() == before
    assert ctx.storage.file_path(fid).read_bytes() == b"hello"
    assert ctx.storage.upload_offset(pending) == 10
    assert ctx.db.used_bytes(b.user_id) == 0


def test_usage_counts_only_own(user: TestClient, other_user: TestClient):
    upload(user, new_share(user)["slug"], b"x" * 100)
    # unfinished uploads count too: their space is already promised
    tus_create(user, new_share(user)["slug"], 50)
    assert user.get("/api/app/usage").json()["used"] == 150
    assert other_user.get("/api/app/usage").json()["used"] == 0
