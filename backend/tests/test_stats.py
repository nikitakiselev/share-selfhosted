from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from share_app.stats import is_bot
from tests.conftest import new_share, upload

BROWSER = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/18.0 Safari/605.1.15"


def _stats(admin: TestClient, slug: str) -> dict:
    return admin.get(f"/api/app/shares/{slug}").json()


@pytest.mark.parametrize("ua", [
    "TelegramBot (like TwitterBot)",
    "WhatsApp/2.23.20.0 A",
    "facebookexternalhit/1.1",
    "Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com)",
    "Slackbot-LinkExpanding 1.0 (+https://api.slack.com/robots)",
    "Mozilla/5.0 (compatible; YandexBot/3.0)",
    "Mozilla/5.0 (compatible; Googlebot/2.1)",
])
def test_bots(ua):
    assert is_bot(ua)


@pytest.mark.parametrize("ua", [
    BROWSER,
    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/129.0 Mobile Safari/537.36 Telegram-Android/11.2",
    "curl/8.7.1",
    "Wget/1.24.5",
    None,
])
def test_not_bots(ua):
    assert not is_bot(ua)


def test_views_dedup_per_ip(admin: TestClient, make_client, fake_clock):
    slug = new_share(admin)["slug"]
    a = make_client("203.0.113.5", headers={"User-Agent": BROWSER})
    b = make_client("203.0.113.6", headers={"User-Agent": BROWSER})
    a.get(f"/api/public/shares/{slug}")
    a.get(f"/api/public/shares/{slug}")
    b.get(f"/api/public/shares/{slug}")
    assert _stats(admin, slug)["views"] == 2
    fake_clock.advance(31 * 60)
    a.get(f"/api/public/shares/{slug}")
    s = _stats(admin, slug)
    assert s["views"] == 3 and s["last_access_at"] == fake_clock.t
    ev = s["events"][0]
    assert ev["kind"] == "view" and ev["ip"] == "203.0.113.5" and ev["user_agent"] == BROWSER


def test_bots_and_owner_not_counted(admin: TestClient, user: TestClient, make_client):
    slug = new_share(admin)["slug"]
    make_client("203.0.113.5", headers={"User-Agent": "TelegramBot (like TwitterBot)"}).get(f"/api/public/shares/{slug}")
    admin.get(f"/api/public/shares/{slug}")
    assert _stats(admin, slug)["views"] == 0
    # another signed-in user is a regular recipient
    user.get(f"/api/public/shares/{slug}")
    assert _stats(admin, slug)["views"] == 1
    # and the owner from outside is not counted: the bypass is by session, not by IP
    own = new_share(user)["slug"]
    user.get(f"/api/public/shares/{own}")
    assert _stats(user, own)["views"] == 0


def test_downloads_counted_from_start_only(admin: TestClient, outsider: TestClient):
    slug = new_share(admin)["slug"]
    upload(admin, slug, b"x" * 100, "a.bin")
    upload(admin, slug, b"y" * 100, "b.bin")
    f = outsider.get(f"/api/public/shares/{slug}").json()["files"][0]
    outsider.get(f["url"])  # an inline view is not a download
    outsider.get(f["download_url"])
    outsider.get(f["download_url"], headers={"Range": "bytes=0-9"})
    outsider.get(f["download_url"], headers={"Range": "bytes=50-"})  # resuming the same download
    outsider.head(f["download_url"])
    s = _stats(admin, slug)
    assert s["downloads"] == 2
    outsider.get(f"/api/public/shares/{slug}/zip")
    s = _stats(admin, slug)
    assert s["downloads"] == 3
    kinds = [e["kind"] for e in s["events"]]
    assert kinds.count("zip") == 1 and kinds.count("download") == 2
    dl = next(e for e in s["events"] if e["kind"] == "download")
    assert dl["file_name"] == "a.bin"


def test_played(admin: TestClient, outsider: TestClient):
    slug = new_share(admin)["slug"]
    fid = upload(admin, slug, b"x", "a.mp4", "video/mp4")
    assert outsider.post(f"/api/public/shares/{slug}/files/{fid}/played").status_code == 204
    assert _stats(admin, slug)["plays"] == 1
