from __future__ import annotations

import base64
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from share_app import accounts, clock
from share_app.app import create_app
from share_app.auth import hash_password
from share_app.config import Settings, parse_nets, parse_proxies
from share_app.quota import GiB

INTERNAL_IP = "192.168.1.10"
EXTERNAL_IP = "203.0.113.5"
BASE_URL = "https://share.test"
INDEX = ('<!doctype html><html lang="ru"><head><meta charset="utf-8"><!--og-->'
         '<script type="module" src="/assets/app.js"></script></head><body><div id="app"></div></body></html>')
TUS = {"Tus-Resumable": "1.0.0"}

# the first admin is created on start from SHARE_ADMIN_EMAIL + SHARE_ADMIN_PASSWORD (username — admin)
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "admin-password-1"
USER_PASSWORD = "correct-horse-battery"
# the hash is computed once — scrypt is not instant
USER_HASH = hash_password(USER_PASSWORD)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text(INDEX, encoding="utf-8")
    (static / "assets" / "app.js").write_text("console.log('share')")
    (static / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    return Settings(
        data_dir=tmp_path / "data",
        static_dir=static,
        secret=b"s" * 32,
        admin_email=ADMIN_EMAIL,
        admin_password=ADMIN_PASSWORD,
        public_url=BASE_URL,
        internal_nets=parse_nets("192.168.1.0/24,10.8.0.0/24"),
        trusted_proxies=parse_proxies("192.168.1.2"),
        background=False,
    )


@pytest.fixture
def app(settings: Settings):
    return create_app(settings)


@pytest.fixture
def ctx(app):
    return app.state.ctx


@pytest.fixture
def make_client(app) -> Iterator[Callable[..., TestClient]]:
    """A client with an IP. Sends its own Origin by default, like a browser: without it
    state-changing requests with a session get 403 bad_origin."""
    clients: list[TestClient] = []

    def factory(ip: str = INTERNAL_IP, *, origin: bool = True, **kw) -> TestClient:
        headers = {"Origin": BASE_URL} if origin else {}
        c = TestClient(app, base_url=BASE_URL, client=(ip, 50000), headers={**headers, **kw.pop("headers", {})},
                       **kw)
        clients.append(c)
        return c

    yield factory
    for c in clients:
        c.close()


@pytest.fixture
def anon(make_client) -> TestClient:
    """An internal client, not signed in."""
    return make_client()


@pytest.fixture
def admin(ctx, make_client) -> TestClient:
    """The owner (admin role) from the internal network — signs in via the API."""
    c = make_client()
    r = c.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 204, r.text
    c.user_id = ctx.db.get_user_by_login("admin")["id"]  # type: ignore[attr-defined]
    return c


@pytest.fixture
def make_user(ctx, make_client) -> Callable[..., TestClient]:
    """A user with a session (email — <login>@example.com). The session is created directly —
    signing in via the API is covered by test_accounts."""

    def factory(login: str, *, quota: int | None = GiB, ip: str = EXTERNAL_IP) -> TestClient:
        uid = ctx.db.create_user(login=login, email=f"{login}@example.com", password_hash=USER_HASH,
                                 quota_bytes=quota, created_at=clock.now())
        c = make_client(ip)
        token = accounts.create_session(ctx.db, uid, clock.now(), ip, "pytest")
        c.cookies.set(accounts.SESSION_COOKIE, token, domain="share.test")
        c.user_id = uid  # type: ignore[attr-defined]
        return c

    return factory


@pytest.fixture
def user(make_user) -> TestClient:
    """A regular user from outside, 1 GiB quota."""
    return make_user("alice")


@pytest.fixture
def other_user(make_user) -> TestClient:
    return make_user("bob")


@pytest.fixture
def outsider(make_client) -> TestClient:
    return make_client(EXTERNAL_IP)


class FakeClock:
    # starts at the real time: fixture sessions are issued by it
    def __init__(self) -> None:
        self.t = int(time.time())

    def __call__(self) -> int:
        return self.t

    def advance(self, seconds: int) -> None:
        self.t += seconds


@pytest.fixture
def fake_clock(monkeypatch) -> FakeClock:
    fc = FakeClock()
    monkeypatch.setattr(clock, "now", fc)
    return fc


def b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def tus_create(client: TestClient, slug: str, length: int, name: str = "file.bin",
               filetype: str = "application/octet-stream", **extra_meta: str):
    meta = {"share": slug, "filename": name, "filetype": filetype, **extra_meta}
    return client.post("/api/app/tus/", headers={
        **TUS, "Upload-Length": str(length), "Upload-Metadata": ",".join(f"{k} {b64(v)}" for k, v in meta.items()),
    })


def tus_patch(client: TestClient, location: str, data: bytes, offset: int):
    return client.patch(location, content=data, headers={
        **TUS, "Upload-Offset": str(offset), "Content-Type": "application/offset+octet-stream",
    })


def upload(client: TestClient, slug: str, data: bytes, name: str = "file.bin",
           filetype: str = "application/octet-stream") -> str:
    r = tus_create(client, slug, len(data), name, filetype)
    assert r.status_code == 201, r.text
    location = r.headers["location"]
    if data:
        r = tus_patch(client, location, data, 0)
        assert r.status_code == 204, r.text
    return location.rsplit("/", 1)[1]


def new_share(client: TestClient, **body) -> dict:
    r = client.post("/api/app/shares", json=body)
    assert r.status_code == 201, r.text
    return r.json()
