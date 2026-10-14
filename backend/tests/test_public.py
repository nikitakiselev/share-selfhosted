from __future__ import annotations

from starlette.testclient import TestClient

from tests.conftest import new_share, upload


def test_card_unprotected(admin: TestClient, outsider: TestClient):
    slug = new_share(admin, title="Фото")["slug"]
    fid = upload(admin, slug, b"12345", "a b.txt", "text/plain")
    body = outsider.get(f"/api/public/shares/{slug}").json()
    assert body["title"] == "Фото" and body["protected"] is False and body["unlocked"] is True
    assert body["file_count"] == 1 and body["total_size"] == 5
    f = body["files"][0]
    assert f["id"] == fid and f["status"] == "ready"
    assert f["url"] == f"/api/public/shares/{slug}/files/{fid}/a%20b.txt"
    assert f["download_url"] == f["url"] + "?download=1"
    assert f["play_url"] is None and f["poster_url"] is None
    assert outsider.get(f["url"]).content == b"12345"


def test_card_protected_hides_everything_until_unlock(admin: TestClient, outsider: TestClient):
    slug = new_share(admin, title="Секрет", password="pw")["slug"]
    fid = upload(admin, slug, b"x", "secret.txt")
    body = outsider.get(f"/api/public/shares/{slug}").json()
    assert body["protected"] and not body["unlocked"]
    assert body["title"] is None and body["files"] == [] and body["total_size"] is None
    url = f"/api/public/shares/{slug}/files/{fid}/secret.txt"
    assert outsider.get(url).json()["error"] == "locked"
    assert outsider.get(f"/api/public/shares/{slug}/zip").status_code == 401

    r = outsider.post(f"/api/public/shares/{slug}/unlock", json={"password": "nope"})
    assert r.status_code == 403 and r.json()["error"] == "wrong_password"
    r = outsider.post(f"/api/public/shares/{slug}/unlock", json={"password": "pw"})
    assert r.status_code == 204
    assert f"share_unlock_{slug}=" in r.headers["set-cookie"]
    body = outsider.get(f"/api/public/shares/{slug}").json()
    assert body["unlocked"] and body["title"] == "Секрет" and len(body["files"]) == 1
    assert outsider.get(url).content == b"x"


def test_password_change_revokes_unlock(admin: TestClient, outsider: TestClient):
    slug = new_share(admin, password="pw")["slug"]
    outsider.post(f"/api/public/shares/{slug}/unlock", json={"password": "pw"})
    assert outsider.get(f"/api/public/shares/{slug}").json()["unlocked"]
    admin.patch(f"/api/app/shares/{slug}", json={"password": "new"})
    assert not outsider.get(f"/api/public/shares/{slug}").json()["unlocked"]


def test_unlock_rate_limit(admin: TestClient, outsider: TestClient):
    slug = new_share(admin, password="pw")["slug"]
    for _ in range(10):
        outsider.post(f"/api/public/shares/{slug}/unlock", json={"password": "x"})
    r = outsider.post(f"/api/public/shares/{slug}/unlock", json={"password": "pw"})
    assert r.status_code == 429


def test_admin_bypasses_password(admin: TestClient):
    slug = new_share(admin, password="pw")["slug"]
    fid = upload(admin, slug, b"x", "a.txt")
    assert admin.get(f"/api/public/shares/{slug}").json()["unlocked"] is True
    assert admin.get(f"/api/public/shares/{slug}/files/{fid}/a.txt").status_code == 200


def test_not_found_and_expired(admin: TestClient, outsider: TestClient, fake_clock):
    assert outsider.get("/api/public/shares/nothing123").json()["error"] == "not_found"
    slug = new_share(admin, expires_at=fake_clock.t + 60)["slug"]
    fid = upload(admin, slug, b"x", "a.txt")
    fake_clock.advance(61)
    r = outsider.get(f"/api/public/shares/{slug}")
    assert r.status_code == 410 and r.json()["error"] == "expired"
    assert r.json()["expired_at"] == fake_clock.t - 1
    assert outsider.get(f"/api/public/shares/{slug}/files/{fid}/a.txt").status_code == 410
    # extending within the window brings the link back
    admin.patch(f"/api/app/shares/{slug}", json={"expires_at": fake_clock.t + 3600})
    assert outsider.get(f"/api/public/shares/{slug}").status_code == 200


def test_uploading_file_hidden_from_recipients(admin: TestClient, outsider: TestClient):
    from tests.conftest import tus_create, tus_patch

    slug = new_share(admin)["slug"]
    loc = tus_create(admin, slug, 4, "big.mkv", "video/x-matroska").headers["location"]
    fid = loc.rsplit("/", 1)[1]
    card = outsider.get(f"/api/public/shares/{slug}").json()
    assert card["files"] == [] and card["file_count"] == 0 and card["total_size"] == 0
    assert "Files are uploading" in outsider.get(f"/s/{slug}").text
    assert outsider.get(f"/api/public/shares/{slug}/files/{fid}/big.mkv").status_code == 404
    # finished uploading — shows up
    assert tus_patch(admin, loc, b"data", 0).status_code == 204
    card = outsider.get(f"/api/public/shares/{slug}").json()
    assert [f["name"] for f in card["files"]] == ["big.mkv"] and card["title"] == "big.mkv"


def test_file_from_other_share_not_served(admin: TestClient, outsider: TestClient):
    a = new_share(admin)["slug"]
    b = new_share(admin)["slug"]
    fid = upload(admin, a, b"x", "a.txt")
    assert outsider.get(f"/api/public/shares/{b}/files/{fid}/a.txt").status_code == 404


def test_reserved_name_segment(admin: TestClient, outsider: TestClient):
    slug = new_share(admin)["slug"]
    upload(admin, slug, b"xyz", "play")
    f = outsider.get(f"/api/public/shares/{slug}").json()["files"][0]
    assert f["url"].endswith("/file-play")
    assert outsider.get(f["url"]).content == b"xyz"


def test_unsafe_types_forced_to_download(admin: TestClient, outsider: TestClient):
    slug = new_share(admin)["slug"]
    upload(admin, slug, b"<script>alert(1)</script>", "x.html", "text/html")
    upload(admin, slug, b"<svg/>", "x.svg", "image/svg+xml")
    upload(admin, slug, b"hi", "x.txt", "text/plain")
    files = outsider.get(f"/api/public/shares/{slug}").json()["files"]
    for f in files[:2]:
        r = outsider.get(f["url"])
        assert r.headers["content-type"] == "application/octet-stream"
        assert r.headers["content-disposition"].startswith("attachment")
        assert r.headers["x-content-type-options"] == "nosniff"
    r = outsider.get(files[2]["url"])
    assert r.headers["content-type"] == "text/plain; charset=utf-8"
    assert r.headers["content-disposition"].startswith("inline")
    assert outsider.get(files[2]["download_url"]).headers["content-disposition"].startswith("attachment")


def test_content_disposition_utf8(admin: TestClient, outsider: TestClient):
    slug = new_share(admin)["slug"]
    upload(admin, slug, b"x", 'видео "1".mp4', "video/mp4")
    f = outsider.get(f"/api/public/shares/{slug}").json()["files"][0]
    cd = outsider.get(f["download_url"]).headers["content-disposition"]
    assert cd.startswith('attachment; filename="')
    assert "filename*=UTF-8''%D0%B2%D0%B8%D0%B4%D0%B5%D0%BE%20%221%22.mp4" in cd
