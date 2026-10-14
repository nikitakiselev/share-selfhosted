from __future__ import annotations

from dataclasses import replace

import pytest
from starlette.testclient import TestClient

from share_app.config import Settings, load_settings
from share_app.fmt import human_size, plural
from tests.conftest import new_share, upload

TEXTS = {
    "en": {"files": "2 files · 2 KB", "video": "Video · 10 B", "protected": "Password-protected files",
           "unavailable": "Link unavailable"},
    "ru": {"files": "2 файла · 2 КБ", "video": "Видео · 10 Б", "protected": "Файлы под паролем",
           "unavailable": "Ссылка недоступна"},
}
LANGS = pytest.mark.parametrize("settings", ["en", "ru"], indirect=True)


@pytest.fixture
def settings(settings: Settings, request) -> Settings:
    """Page language from `@LANGS`; English by default, as in the config."""
    return replace(settings, language=getattr(request, "param", "en"))


@LANGS
def test_spa_routes(anon: TestClient, settings: Settings):
    for path in ("/", "/shares", "/shares/abc", "/users", "/invite/abc", "/reset/abc"):
        r = anon.get(path)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
        assert "<title>Share</title>" in r.text and "<!--og-->" not in r.text
        assert 'name="robots" content="noindex, nofollow"' in r.text
        # the built index.html has its own lang — the server's one replaces it
        assert r.text.count("lang=") == 1 and f'<html lang="{settings.language}">' in r.text


def test_assets_cached_and_traversal_blocked(outsider: TestClient):
    r = outsider.get("/assets/app.js")
    assert r.status_code == 200 and "immutable" in r.headers["cache-control"]
    assert outsider.get("/assets/../index.html").status_code in (403, 404)
    assert outsider.get("/assets/%2e%2e/index.html").status_code == 404
    assert outsider.get("/assets/missing.js").status_code == 404


@LANGS
def test_og_unprotected_with_escaping(admin: TestClient, outsider: TestClient, ctx, settings: Settings):
    slug = new_share(admin, title='<b>"Отпуск"</b>')["slug"]
    fid = upload(admin, slug, b"x" * 2048, "a.mp4", "video/mp4")
    upload(admin, slug, b"y", "b.txt")
    ctx.db.update_file(fid, has_poster=1)
    html = outsider.get(f"/s/{slug}").text
    assert f'<html lang="{settings.language}">' in html
    assert "<title>&lt;b&gt;&quot;Отпуск&quot;&lt;/b&gt;</title>" in html
    assert 'property="og:title" content="&lt;b&gt;&quot;Отпуск&quot;&lt;/b&gt;"' in html
    assert f'property="og:description" content="{TEXTS[settings.language]["files"]}"' in html
    assert f'property="og:image" content="https://share.test/api/public/shares/{slug}/files/{fid}/poster.jpg"' in html
    assert f'property="og:url" content="https://share.test/s/{slug}"' in html
    assert 'name="twitter:card" content="summary_large_image"' in html


@LANGS
def test_og_single_video(admin: TestClient, outsider: TestClient, settings: Settings):
    slug = new_share(admin)["slug"]
    upload(admin, slug, b"x" * 10, "кино.mkv", "video/x-matroska")
    html = outsider.get(f"/s/{slug}").text
    assert f'content="{TEXTS[settings.language]["video"]}"' in html and "<title>кино.mkv</title>" in html


@LANGS
def test_og_protected_reveals_nothing(admin: TestClient, outsider: TestClient, settings: Settings):
    slug = new_share(admin, title="Тайна", password="pw")["slug"]
    upload(admin, slug, b"x", "secret-name.mp4", "video/mp4")
    html = outsider.get(f"/s/{slug}").text
    assert TEXTS[settings.language]["protected"] in html
    assert "Тайна" not in html and "secret-name" not in html and "og:image" not in html


@LANGS
def test_og_missing_share(outsider: TestClient, settings: Settings):
    html = outsider.get("/s/doesnotexist").text
    assert f'<html lang="{settings.language}">' in html
    assert TEXTS[settings.language]["unavailable"] in html


def test_human_size_and_plural():
    assert human_size(512) == "512 B"
    assert human_size(1536) == "1.5 KB"
    assert human_size(1288490189) == "1.2 GB"
    assert human_size(350 * 1024 * 1024) == "350 MB"
    assert human_size(1023 * 1024) == "1023 KB"
    assert human_size(1024**3 - 12) == "1 GB"  # not "1024 MB": the unit is picked after rounding
    assert human_size(512, "ru") == "512 Б"
    assert human_size(1536, "ru") == "1,5 КБ"
    assert human_size(1288490189, "ru") == "1,2 ГБ"
    assert human_size(350 * 1024 * 1024, "ru") == "350 МБ"
    assert human_size(1024**3 - 12, "ru") == "1 ГБ"
    assert [plural(n, "en", ("file", "files")) for n in (0, 1, 2, 11, 21)] == [
        "files", "file", "files", "files", "files",
    ]
    assert [plural(n, "ru", ("файл", "файла", "файлов")) for n in (1, 2, 5, 11, 21, 22, 112)] == [
        "файл", "файла", "файлов", "файлов", "файл", "файла", "файлов",
    ]


def test_language_setting():
    env = {"SHARE_SECRET": "s" * 32, "SHARE_PUBLIC_URL": "https://share.example.com"}
    assert load_settings(env).language == "en"
    assert load_settings({**env, "SHARE_LANGUAGE": " RU "}).language == "ru"
    with pytest.raises(ValueError, match="SHARE_LANGUAGE"):
        load_settings({**env, "SHARE_LANGUAGE": "de"})
