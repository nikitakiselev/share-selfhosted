from __future__ import annotations

import io
import os
from pathlib import Path

import pytest

from share_app import accounts, clock
from share_app.auth import verify_password
from share_app.db import Database
from share_app.main import main
from share_app.quota import GiB
from tests.conftest import USER_HASH, USER_PASSWORD

OWNER = "admin@example.com"


@pytest.fixture
def env(monkeypatch, tmp_path) -> Path:
    for key in [k for k in os.environ if k.startswith("SHARE_")]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("SHARE_SECRET", "s" * 32)
    monkeypatch.setenv("SHARE_PUBLIC_URL", "https://share.example.com")
    monkeypatch.setenv("SHARE_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


@pytest.fixture
def data_dir(env: Path) -> Path:
    env.mkdir()
    db = Database(env / "share.db")
    db.create_user(login="admin", email=OWNER, password_hash=USER_HASH, role="admin", quota_bytes=None,
                   created_at=clock.now())
    db.create_user(login="alice", email="alice@example.com", password_hash=USER_HASH, quota_bytes=GiB,
                   created_at=clock.now())
    db.close()
    return env


def _run(monkeypatch, *args: str, stdin: str = "") -> int:
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    return main(list(args))


def test_set_password(data_dir: Path, monkeypatch, capsys):
    db = Database(data_dir / "share.db")
    uid = db.get_user_by_email(OWNER)["id"]
    accounts.create_session(db, uid, clock.now(), None, None)
    db.close()

    assert _run(monkeypatch, "set-password", "--email", " Admin@Example.COM ", stdin="new-password-1\n") == 0
    db = Database(data_dir / "share.db")
    assert verify_password("new-password-1", db.get_user(uid)["password_hash"])
    assert db.user_sessions(uid) == []
    assert verify_password(USER_PASSWORD, db.get_user_by_email("alice@example.com")["password_hash"])
    db.close()

    assert _run(monkeypatch, "set-password", "--email", OWNER, stdin="short\n") == 2
    assert _run(monkeypatch, "set-password", "--email", "not-an-email", stdin="whatever-password\n") == 2
    capsys.readouterr()
    assert _run(monkeypatch, "set-password", "--email", "stranger@example.com", stdin="whatever-password\n") == 1
    assert "no user" in capsys.readouterr().err


def test_set_email(data_dir: Path, monkeypatch, capsys):
    assert _run(monkeypatch, "set-email", "--email", OWNER, "--new-email", " Owner@Example.COM ") == 0
    db = Database(data_dir / "share.db")
    assert db.get_user_by_login("admin")["email"] == "owner@example.com"
    db.close()

    capsys.readouterr()
    assert _run(monkeypatch, "set-email", "--email", "owner@example.com", "--new-email", "ALICE@example.com") == 1
    assert "already taken" in capsys.readouterr().err
    assert _run(monkeypatch, "set-email", "--email", "stranger@example.com", "--new-email", "s@example.com") == 1
    assert "no user" in capsys.readouterr().err
    assert _run(monkeypatch, "set-email", "--email", "owner@example.com", "--new-email", "not-an-email") == 2
    # the same email again is not an error
    assert _run(monkeypatch, "set-email", "--email", "owner@example.com", "--new-email", "owner@example.com") == 0


def test_unknown_command(monkeypatch, capsys):
    assert _run(monkeypatch, "set-password") == 2
    assert "usage:" in capsys.readouterr().err


def test_serve_without_first_admin(env: Path, monkeypatch, capsys):
    assert _run(monkeypatch) == 2
    assert "no users yet" in capsys.readouterr().err
    monkeypatch.delenv("SHARE_PUBLIC_URL")
    assert _run(monkeypatch) == 2
    assert "SHARE_PUBLIC_URL is not set" in capsys.readouterr().err
