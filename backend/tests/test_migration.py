from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from share_app.db import SCHEMA_VERSION, Database


def _version(path: Path) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def test_fresh_install_gets_current_schema(tmp_path: Path):
    path = tmp_path / "share.db"
    db = Database(path)
    assert db.count_users() == 0
    db.close()
    assert _version(path) == SCHEMA_VERSION
    # reopening the current schema changes nothing
    db = Database(path)
    db.create_user(login="admin", email="admin@example.com", password_hash="x", role="admin",
                   quota_bytes=None, created_at=1)
    db.close()
    db = Database(path)
    assert db.get_user_by_email("admin@example.com")["role"] == "admin"
    db.close()


@pytest.mark.parametrize("version", [1, 3, SCHEMA_VERSION + 1])
def test_other_schema_versions_are_refused(tmp_path: Path, version: int):
    path = tmp_path / "share.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE shares (slug TEXT PRIMARY KEY)")
    conn.execute(f"PRAGMA user_version = {version}")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match=f"schema v{version} is not supported"):
        Database(path)
    # the database is left as it was
    assert _version(path) == version
