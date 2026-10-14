from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from share_app import auth
from share_app.app import admin_login, create_app
from share_app.config import Settings, load_settings
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD, BASE_URL, INTERNAL_IP

ENV = {"SHARE_SECRET": "s" * 32, "SHARE_PUBLIC_URL": "https://share.example.com"}


def test_defaults():
    s = load_settings(ENV)
    assert s.data_dir == Path("/data") and s.static_dir == Path("/app/static")
    # proxies are trusted from the same private networks as the admin panel
    for ip in ("172.17.0.1", "10.0.0.2", "192.168.1.1", "127.0.0.1", "::1"):
        assert auth.in_nets(ip, s.trusted_proxies), ip
    assert not auth.in_nets("203.0.113.5", s.trusted_proxies)
    assert s.cookie_secure is True
    assert s.admin_email is None and s.admin_password is None
    for ip in ("10.1.2.3", "172.20.0.5", "192.168.1.10", "fd00::1", "127.0.0.1", "::1"):
        assert auth.is_internal(ip, s.internal_nets), ip
    for ip in ("203.0.113.5", "172.32.0.1", "2001:db8::1"):
        assert not auth.is_internal(ip, s.internal_nets), ip


def test_public_url_required():
    env = {"SHARE_SECRET": "s" * 32}
    with pytest.raises(ValueError, match="SHARE_PUBLIC_URL is not set"):
        load_settings(env)
    for bad in ("share.example.com", "ftp://share.example.com", "https://"):
        with pytest.raises(ValueError, match="SHARE_PUBLIC_URL"):
            load_settings({**env, "SHARE_PUBLIC_URL": bad})
    assert load_settings({**env, "SHARE_PUBLIC_URL": " https://share.example.com/ "}).public_url == \
        "https://share.example.com"


def test_cookie_secure_follows_public_url():
    http = {**ENV, "SHARE_PUBLIC_URL": "http://192.168.1.5:8000"}
    assert load_settings(http).cookie_secure is False
    assert load_settings({**http, "SHARE_COOKIE_SECURE": "1"}).cookie_secure is True
    assert load_settings({**ENV, "SHARE_COOKIE_SECURE": "0"}).cookie_secure is False


def test_trusted_proxies():
    s = load_settings({**ENV, "SHARE_TRUSTED_PROXIES": "10.0.0.2, 172.18.0.0/16"})
    assert auth.in_nets("10.0.0.2", s.trusted_proxies) and auth.in_nets("172.18.5.5", s.trusted_proxies)
    assert not auth.in_nets("10.0.0.3", s.trusted_proxies) and not auth.in_nets("127.0.0.1", s.trusted_proxies)
    with pytest.raises(ValueError, match="SHARE_TRUSTED_PROXIES"):
        load_settings({**ENV, "SHARE_TRUSTED_PROXIES": "proxy.lan"})


def test_admin_settings():
    assert load_settings({**ENV, "SHARE_ADMIN_EMAIL": " Owner@Example.COM "}).admin_email == "owner@example.com"
    assert load_settings({**ENV, "SHARE_ADMIN_EMAIL": "  "}).admin_email is None
    for bad in ("owner", "a@b", "a b@c.d", "x@" + "y" * 250 + ".ru"):
        with pytest.raises(ValueError, match="SHARE_ADMIN_EMAIL"):
            load_settings({**ENV, "SHARE_ADMIN_EMAIL": bad})
    s = load_settings({**ENV, "SHARE_ADMIN_PASSWORD": ADMIN_PASSWORD})
    assert s.admin_password == ADMIN_PASSWORD and ADMIN_PASSWORD not in repr(s)


# --- first admin ---

def test_first_admin_created_on_empty_db(settings: Settings):
    app = create_app(settings)
    [owner] = app.state.ctx.db.list_users()
    assert owner["login"] == "admin" and owner["email"] == ADMIN_EMAIL
    assert owner["role"] == "admin" and owner["quota_bytes"] is None
    with TestClient(app, base_url=BASE_URL, client=(INTERNAL_IP, 1), headers={"Origin": BASE_URL}) as c:
        assert c.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}).status_code == 204
        assert c.get("/api/admin/users").status_code == 200


def test_admin_variables_ignored_once_users_exist(settings: Settings, caplog):
    create_app(settings).state.ctx.db.close()
    caplog.set_level(logging.INFO, logger="share")
    db = create_app(replace(settings, admin_email="other@example.com", admin_password="other-password-1")).state.ctx.db
    [owner] = db.list_users()
    assert owner["email"] == ADMIN_EMAIL and auth.verify_password(ADMIN_PASSWORD, owner["password_hash"])
    db.close()
    assert "SHARE_ADMIN_PASSWORD is ignored" in caplog.text
    caplog.clear()
    create_app(replace(settings, admin_email=None, admin_password=None)).state.ctx.db.close()
    assert caplog.text == ""


@pytest.mark.parametrize("changes", [{"admin_email": None}, {"admin_password": None},
                                     {"admin_email": None, "admin_password": None}])
def test_no_users_and_no_admin_variables(settings: Settings, changes: dict):
    with pytest.raises(ValueError, match="no users yet: set SHARE_ADMIN_EMAIL and SHARE_ADMIN_PASSWORD"):
        create_app(replace(settings, **changes))
    # nothing was created: with the variables the next start succeeds
    assert len(create_app(settings).state.ctx.db.list_users()) == 1


def test_short_admin_password(settings: Settings):
    with pytest.raises(ValueError, match="SHARE_ADMIN_PASSWORD must be 10"):
        create_app(replace(settings, admin_password="short"))


@pytest.mark.parametrize(("email", "login"), [
    ("admin@example.com", "admin"),
    ("John.Smith+share@example.com", "john.smith-share"),
    ("ab@example.com", "admin"),
    ("иван@example.com", "admin"),
    ("x" * 40 + "@example.com", "x" * 32),
])
def test_admin_login(email: str, login: str):
    assert admin_login(email) == login
