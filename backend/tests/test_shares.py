from __future__ import annotations

from starlette.testclient import TestClient

from tests.conftest import new_share, tus_create, tus_patch, upload


def test_create_share_summary(admin: TestClient, fake_clock):
    body = new_share(admin, title="  Отпуск  ", expires_at=fake_clock.t + 3600, password="pw")
    assert len(body["slug"]) == 10 and body["slug"].isalnum()
    assert body["url"] == f"https://share.test/s/{body['slug']}"
    assert body["title"] == "Отпуск" and body["display_title"] == "Отпуск"
    assert body["protected"] is True and body["expired"] is False
    assert body["file_count"] == 0 and body["total_size"] == 0 and body["uploading_count"] == 0
    assert body["views"] == 0 and body["last_access_at"] is None


def test_create_validation(admin: TestClient, fake_clock):
    assert admin.post("/api/app/shares", json={"expires_at": fake_clock.t - 1}).json()["error"] == "expires_in_past"
    assert admin.post("/api/app/shares", json={"expires_at": "завтра"}).status_code == 400
    assert admin.post("/api/app/shares", json={"password": ""}).status_code == 400
    r = admin.post("/api/app/shares", json={"title": "x" * 201})
    assert r.status_code == 400 and r.json()["error"] == "bad_title" and r.json()["max_length"] == 200
    assert admin.post("/api/app/shares", content=b"not json").status_code == 400


def test_display_title_falls_back_to_first_file(admin: TestClient):
    slug = new_share(admin)["slug"]
    upload(admin, slug, b"1", "первый.mp4", "video/mp4")
    upload(admin, slug, b"2", "второй.txt")
    s = admin.get(f"/api/app/shares/{slug}").json()
    assert s["title"] is None and s["display_title"] == "первый.mp4"
    assert s["file_count"] == 2 and s["total_size"] == 2


def test_list_newest_first_with_usage(admin: TestClient, fake_clock):
    a = new_share(admin)["slug"]
    fake_clock.advance(10)
    b = new_share(admin)["slug"]
    upload(admin, a, b"12345")
    body = admin.get("/api/app/shares").json()
    assert [s["slug"] for s in body["shares"]] == [b, a]
    usage = body["usage"]
    assert usage["quota"] is None and usage["free"] is None
    assert usage["used"] == 5 and set(usage["disk"]) == {"used", "total", "free"}
    assert admin.get("/api/app/usage").json()["disk"]["total"] > 0


def test_usage_for_user(user: TestClient):
    u = user.get("/api/app/usage").json()
    assert u == {"quota": 1 << 30, "used": 0, "free": 1 << 30, "disk": None}
    assert user.get("/api/app/shares").json() == {"shares": [], "usage": u}


def test_patch_only_sent_keys(admin: TestClient, fake_clock):
    slug = new_share(admin, title="A", expires_at=fake_clock.t + 100)["slug"]
    s = admin.patch(f"/api/app/shares/{slug}", json={"title": "B"}).json()
    assert s["title"] == "B" and s["expires_at"] == fake_clock.t + 100
    s = admin.patch(f"/api/app/shares/{slug}", json={"expires_at": None}).json()
    assert s["expires_at"] is None and s["title"] == "B"
    s = admin.patch(f"/api/app/shares/{slug}", json={"password": "x"}).json()
    assert s["protected"] is True
    s = admin.patch(f"/api/app/shares/{slug}", json={"password": None}).json()
    assert s["protected"] is False
    assert admin.patch("/api/app/shares/missing", json={}).status_code == 404


def test_detail_has_files_and_upload_progress(admin: TestClient):
    slug = new_share(admin)["slug"]
    upload(admin, slug, b"done", "a.txt", "text/plain")
    loc = tus_create(admin, slug, 100, "b.bin").headers["location"]
    admin.patch(loc, content=b"x" * 30, headers={"Tus-Resumable": "1.0.0", "Upload-Offset": "0",
                                                  "Content-Type": "application/offset+octet-stream"})
    d = admin.get(f"/api/app/shares/{slug}").json()
    files = {f["name"]: f for f in d["files"]}
    assert files["a.txt"]["uploaded"] == 4 and files["a.txt"]["status"] == "ready"
    assert files["b.bin"]["uploaded"] == 30 and files["b.bin"]["status"] == "uploading"
    assert files["b.bin"]["url"] is None
    assert d["uploading_count"] == 1
    assert d["events"] == []


def test_delete_share_removes_everything(admin: TestClient, ctx):
    slug = new_share(admin)["slug"]
    done = upload(admin, slug, b"data", "a.txt")
    loc = tus_create(admin, slug, 100).headers["location"]
    partial = loc.rsplit("/", 1)[1]
    assert admin.delete(f"/api/app/shares/{slug}").status_code == 204
    assert ctx.db.get_share(slug) is None
    assert ctx.db.get_file(done) is None and ctx.db.get_file(partial) is None
    assert not ctx.storage.file_path(done).exists()
    assert not ctx.storage.upload_path(partial).exists()
    assert admin.delete(f"/api/app/shares/{slug}").status_code == 404


def test_delete_single_file(admin: TestClient, ctx):
    slug = new_share(admin)["slug"]
    a = upload(admin, slug, b"a", "a.txt")
    b = upload(admin, slug, b"b", "b.txt")
    assert admin.delete(f"/api/app/shares/{slug}/files/{a}").status_code == 204
    assert not ctx.storage.file_path(a).exists()
    assert [f["id"] for f in admin.get(f"/api/app/shares/{slug}").json()["files"]] == [b]
    other = new_share(admin)["slug"]
    # a file of someone else's link cannot be deleted through this path
    assert admin.delete(f"/api/app/shares/{other}/files/{b}").status_code == 404


def test_rename_file(admin: TestClient, outsider: TestClient, ctx):
    slug = new_share(admin)["slug"]
    fid = upload(admin, slug, b"video", "IMG_0042.mp4", "video/mp4")
    url = f"/api/app/shares/{slug}/files/{fid}"
    f = admin.patch(url, json={"name": "  Отпуск 2026/день 1.mp4  "}).json()
    assert f["name"] == "Отпуск 2026_день 1.mp4"
    assert f["kind"] == "video" and f["mime"] == "video/mp4"
    assert f["url"].endswith("/%D0%9E%D1%82%D0%BF%D1%83%D1%81%D0%BA%202026_%D0%B4%D0%B5%D0%BD%D1%8C%201.mp4")
    # the recipient downloads under the new name, the file on disk is untouched
    r = outsider.get(f["download_url"])
    assert r.status_code == 200 and "filename*=UTF-8''%D0%9E%D1%82%D0%BF" in r.headers["content-disposition"]
    assert ctx.storage.file_path(fid).read_bytes() == b"video"
    # the first file sets the link's default title
    assert admin.get(f"/api/app/shares/{slug}").json()["display_title"] == "Отпуск 2026_день 1.mp4"
    # the kind stays from the upload even if the extension changed
    assert admin.patch(url, json={"name": "notes.txt"}).json()["kind"] == "video"


def test_rename_file_validation(admin: TestClient, anon: TestClient):
    slug = new_share(admin)["slug"]
    fid = upload(admin, slug, b"x", "a.txt")
    url = f"/api/app/shares/{slug}/files/{fid}"
    for bad in ("", "   ", "..", "x" * 256, 42, None):
        r = admin.patch(url, json={"name": bad})
        assert r.json()["error"] == "bad_name" and r.json()["max_length"] == 255, bad
    assert admin.patch(url, json={}).json()["name"] == "a.txt"
    assert anon.patch(url, json={"name": "b.txt"}).status_code == 401
    other = new_share(admin)["slug"]
    assert admin.patch(f"/api/app/shares/{other}/files/{fid}", json={"name": "b.txt"}).status_code == 404
    assert admin.patch(f"/api/app/shares/{slug}/files/missing", json={"name": "b.txt"}).status_code == 404


def test_rename_while_uploading(admin: TestClient, ctx):
    slug = new_share(admin)["slug"]
    loc = tus_create(admin, slug, 10, "raw.bin").headers["location"]
    fid = loc.rsplit("/", 1)[1]
    f = admin.patch(f"/api/app/shares/{slug}/files/{fid}", json={"name": "готово.bin"}).json()
    assert f["name"] == "готово.bin" and f["status"] == "uploading" and f["url"] is None
    assert tus_patch(admin, loc, b"0123456789", 0).status_code == 204
    assert ctx.db.get_file(fid)["name"] == "готово.bin"

