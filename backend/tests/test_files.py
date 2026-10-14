from __future__ import annotations

import io
import zipfile

import pytest
from starlette.testclient import TestClient

from share_app.files import parse_range
from tests.conftest import new_share, upload

DATA = bytes(range(256)) * 40  # 10240 bytes


@pytest.fixture
def file_url(admin: TestClient) -> str:
    slug = new_share(admin)["slug"]
    upload(admin, slug, DATA, "clip.mp4", "video/mp4")
    return admin.get(f"/api/public/shares/{slug}").json()["files"][0]["url"]


@pytest.mark.parametrize("header,size,expected", [
    (None, 100, None),
    ("bytes=0-9", 100, (0, 9)),
    ("bytes=90-", 100, (90, 99)),
    ("bytes=-10", 100, (90, 99)),
    ("bytes=-500", 100, (0, 99)),
    ("bytes=50-1000", 100, (50, 99)),
    ("bytes=100-", 100, "unsatisfiable"),
    ("bytes=-0", 100, "unsatisfiable"),
    ("bytes=0-1,5-6", 100, None),
    ("bytes=9-3", 100, None),
    ("items=0-1", 100, None),
    ("bytes=0-", 0, "unsatisfiable"),
])
def test_parse_range(header, size, expected):
    assert parse_range(header, size) == expected


def test_full_and_ranges(outsider: TestClient, file_url: str):
    r = outsider.get(file_url)
    assert r.status_code == 200 and r.content == DATA
    assert r.headers["accept-ranges"] == "bytes" and r.headers["content-length"] == str(len(DATA))
    assert r.headers["content-type"] == "video/mp4"

    r = outsider.get(file_url, headers={"Range": "bytes=10-19"})
    assert r.status_code == 206 and r.content == DATA[10:20]
    assert r.headers["content-range"] == f"bytes 10-19/{len(DATA)}"

    r = outsider.get(file_url, headers={"Range": "bytes=-16"})
    assert r.status_code == 206 and r.content == DATA[-16:]

    r = outsider.get(file_url, headers={"Range": "bytes=10000-"})
    assert r.status_code == 206 and r.content == DATA[10000:]

    r = outsider.get(file_url, headers={"Range": "bytes=99999-"})
    assert r.status_code == 416 and r.headers["content-range"] == f"bytes */{len(DATA)}"


def test_head_etag_if_range(outsider: TestClient, file_url: str):
    h = outsider.head(file_url)
    assert h.status_code == 200 and h.headers["content-length"] == str(len(DATA)) and h.content == b""
    etag = h.headers["etag"]
    assert outsider.get(file_url, headers={"If-None-Match": etag}).status_code == 304
    r = outsider.get(file_url, headers={"Range": "bytes=0-9", "If-Range": etag})
    assert r.status_code == 206
    r = outsider.get(file_url, headers={"Range": "bytes=0-9", "If-Range": '"stale"'})
    assert r.status_code == 200 and r.content == DATA


def test_large_file_streams_in_chunks(admin: TestClient, outsider: TestClient):
    big = b"z" * (3 * (1 << 20) + 123)
    slug = new_share(admin)["slug"]
    upload(admin, slug, big, "big.bin")
    url = outsider.get(f"/api/public/shares/{slug}").json()["files"][0]["url"]
    with outsider.stream("GET", url) as r:
        sizes = [len(c) for c in r.iter_raw()]
    assert sum(sizes) == len(big)


def test_zip(admin: TestClient, outsider: TestClient):
    slug = new_share(admin, title="Архив: всё/сразу")["slug"]
    upload(admin, slug, b"one", "a.txt")
    upload(admin, slug, b"two", "a.txt")
    upload(admin, slug, b"three", "b.txt")
    r = outsider.get(f"/api/public/shares/{slug}/zip")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert int(r.headers["content-length"]) == len(r.content)
    # ":" and "/" are not allowed in the archive name — replaced with "_"
    assert "filename*=UTF-8''%D0%90%D1%80%D1%85%D0%B8%D0%B2_%20%D0%B2%D1%81%D1%91_%D1%81%D1%80%D0%B0%D0%B7%D1%83.zip" in \
        r.headers["content-disposition"]
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert zf.namelist() == ["a.txt", "a (2).txt", "b.txt"]
    assert zf.read("a (2).txt") == b"two"
    h = outsider.head(f"/api/public/shares/{slug}/zip")
    assert h.headers["content-length"] == r.headers["content-length"]


def test_zip_skips_uploading_and_404_when_empty(admin: TestClient, outsider: TestClient):
    from tests.conftest import tus_create

    slug = new_share(admin)["slug"]
    tus_create(admin, slug, 100, "partial.bin")
    assert outsider.get(f"/api/public/shares/{slug}/zip").status_code == 404
    upload(admin, slug, b"ok", "ok.txt")
    zf = zipfile.ZipFile(io.BytesIO(outsider.get(f"/api/public/shares/{slug}/zip").content))
    assert zf.namelist() == ["ok.txt"]


def test_unique_names():
    from share_app.zipper import unique_names

    assert unique_names(["a.txt", "A.txt", "a.txt", "b", "b", ".rc", ".rc"]) == [
        "a.txt", "A (2).txt", "a (3).txt", "b", "b (2)", ".rc", ".rc (2)",
    ]
