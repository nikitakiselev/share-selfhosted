"""SQLite: schema and every query of the application.

One connection per process behind a lock: queries are short, and request handlers,
the media worker and cleanup threads all write here.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 4

# shares references users, so users goes first
SCHEMA = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    login TEXT NOT NULL UNIQUE COLLATE NOCASE,
    -- users sign in with it, stored lowercase
    email TEXT,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    -- storage quota in bytes, NULL — unlimited
    quota_bytes INTEGER,
    blocked_at INTEGER,
    created_at INTEGER NOT NULL,
    last_login_at INTEGER
);
CREATE UNIQUE INDEX users_email ON users(email) WHERE email IS NOT NULL;

CREATE TABLE shares (
    slug TEXT PRIMARY KEY,
    title TEXT,
    created_at INTEGER NOT NULL,
    expires_at INTEGER,
    password_hash TEXT,
    password_version INTEGER NOT NULL DEFAULT 0,
    views INTEGER NOT NULL DEFAULT 0,
    downloads INTEGER NOT NULL DEFAULT 0,
    plays INTEGER NOT NULL DEFAULT 0,
    last_access_at INTEGER,
    owner_id INTEGER REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX shares_owner ON shares(owner_id, created_at);

CREATE TABLE files (
    id TEXT PRIMARY KEY,
    share_slug TEXT NOT NULL REFERENCES shares(slug) ON DELETE CASCADE,
    name TEXT NOT NULL,
    size INTEGER NOT NULL,
    mime TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    media_status TEXT NOT NULL DEFAULT 'none',
    play TEXT NOT NULL DEFAULT 'none',
    playable TEXT NOT NULL DEFAULT 'no',
    duration REAL,
    width INTEGER,
    height INTEGER,
    video_codec TEXT,
    audio_codec TEXT,
    has_poster INTEGER NOT NULL DEFAULT 0,
    position INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    completed_at INTEGER,
    last_modified INTEGER
);
CREATE INDEX files_share ON files(share_slug, position);
CREATE INDEX files_media ON files(media_status, completed_at);

CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    share_slug TEXT NOT NULL REFERENCES shares(slug) ON DELETE CASCADE,
    ts INTEGER NOT NULL,
    kind TEXT NOT NULL,
    file_id TEXT,
    ip TEXT,
    user_agent TEXT
);
CREATE INDEX events_share ON events(share_slug, ts);

CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    ip TEXT,
    user_agent TEXT
);
CREATE INDEX sessions_user ON sessions(user_id);

CREATE TABLE tokens (
    id INTEGER PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    email TEXT,
    -- quota the invited user gets (NULL — unlimited)
    quota_bytes INTEGER,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    used_at INTEGER
);
"""

SHARE_AGGREGATES = """
SELECT s.*,
    (SELECT COUNT(*) FROM files f WHERE f.share_slug = s.slug) AS file_count,
    (SELECT COALESCE(SUM(f.size), 0) FROM files f WHERE f.share_slug = s.slug) AS total_size,
    (SELECT COUNT(*) FROM files f WHERE f.share_slug = s.slug AND f.status = 'uploading') AS uploading_count,
    (SELECT f.name FROM files f WHERE f.share_slug = s.slug ORDER BY f.position LIMIT 1) AS first_name
FROM shares s
"""

USERS_WITH_USAGE = """
SELECT u.*,
    (SELECT COUNT(*) FROM shares s WHERE s.owner_id = u.id) AS share_count,
    (SELECT COALESCE(SUM(f.size), 0) FROM files f JOIN shares s ON s.slug = f.share_slug
     WHERE s.owner_id = u.id) AS used
FROM users u
"""

SHARE_FIELDS = {"title", "expires_at", "password_hash", "password_version"}
FILE_FIELDS = {
    "name", "size", "mime", "kind", "status", "media_status", "play", "playable", "duration",
    "width", "height", "video_codec", "audio_codec", "has_poster", "completed_at",
}
USER_FIELDS = {"email", "password_hash", "quota_bytes", "blocked_at", "last_login_at"}
COUNTERS = {"view": "views", "download": "downloads", "zip": "downloads", "play": "plays"}


class Database:
    def __init__(self, path: Path | str) -> None:
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            try:
                self._migrate()
            except BaseException:
                self._conn.close()
                raise
            self._conn.execute("PRAGMA foreign_keys=ON")

    def _migrate(self) -> None:
        """An empty database gets the current schema. There are no upgrades from older
        versions: every published release starts at this one."""
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version == SCHEMA_VERSION:
            return
        if version != 0:
            raise RuntimeError(f"database schema v{version} is not supported: this version of share "
                               f"works with v{SCHEMA_VERSION} only")
        with self.transaction() as conn:
            # executescript commits on its own, so one statement at a time inside the transaction
            for stmt in (s.strip() for s in SCHEMA.split(";")):
                if stmt:
                    conn.execute(stmt)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def _all(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def _one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def _exec(self, sql: str, params: tuple = ()) -> int:
        with self._lock:
            return self._conn.execute(sql, params).rowcount

    # --- users ---

    def create_user(self, *, login: str, password_hash: str, email: str | None = None, role: str = "user",
                    quota_bytes: int | None, created_at: int) -> int:
        with self.transaction() as conn:
            return self._insert_user(conn, login, email, password_hash, role, quota_bytes, created_at)

    @staticmethod
    def _insert_user(conn: sqlite3.Connection, login: str, email: str | None, password_hash: str, role: str,
                     quota_bytes: int | None, created_at: int) -> int:
        cur = conn.execute(
            "INSERT INTO users (login, email, password_hash, role, quota_bytes, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (login, email, password_hash, role, quota_bytes, created_at),
        )
        return int(cur.lastrowid or 0)

    def get_user(self, user_id: int) -> dict[str, Any] | None:
        return self._one("SELECT * FROM users WHERE id = ?", (user_id,))

    def get_user_by_login(self, login: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM users WHERE login = ?", (login,))

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        """email is already normalized (lowercase)."""
        return self._one("SELECT * FROM users WHERE email = ?", (email,))

    def list_users(self) -> list[dict[str, Any]]:
        return self._all(USERS_WITH_USAGE + " ORDER BY u.created_at, u.id")

    def user_with_usage(self, user_id: int) -> dict[str, Any] | None:
        return self._one(USERS_WITH_USAGE + " WHERE u.id = ?", (user_id,))

    def count_users(self) -> int:
        return self._one("SELECT COUNT(*) AS n FROM users")["n"]  # type: ignore[index]

    def update_user(self, user_id: int, **fields: Any) -> None:
        unknown = set(fields) - USER_FIELDS
        if unknown:
            raise ValueError(f"unknown user fields: {unknown}")
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        self._exec(f"UPDATE users SET {cols} WHERE id = ?", (*fields.values(), user_id))

    def delete_user(self, user_id: int) -> list[str]:
        """Deletes the user with their shares, files and sessions; returns file ids to remove from disk."""
        with self.transaction() as conn:
            ids = [r[0] for r in conn.execute(
                "SELECT f.id FROM files f JOIN shares s ON s.slug = f.share_slug WHERE s.owner_id = ?", (user_id,))]
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return ids

    def used_bytes(self, user_id: int) -> int:
        row = self._one(
            "SELECT COALESCE(SUM(f.size), 0) AS used FROM files f JOIN shares s ON s.slug = f.share_slug "
            "WHERE s.owner_id = ?", (user_id,))
        return int(row["used"]) if row else 0

    # --- sessions ---

    def add_session(self, token_hash: str, user_id: int, *, now: int, expires_at: int, ip: str | None,
                    user_agent: str | None) -> None:
        self._exec(
            "INSERT INTO sessions (token_hash, user_id, created_at, last_seen_at, expires_at, ip, user_agent) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (token_hash, user_id, now, now, expires_at, ip, user_agent),
        )

    def session_user(self, token_hash: str) -> dict[str, Any] | None:
        """The session's user; session fields are prefixed with session_."""
        return self._one(
            "SELECT u.*, s.token_hash AS session_hash, s.expires_at AS session_expires_at, "
            "s.last_seen_at AS session_last_seen_at "
            "FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?",
            (token_hash,),
        )

    def touch_session(self, token_hash: str, now: int) -> None:
        self._exec("UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?", (now, token_hash))

    def delete_session(self, token_hash: str) -> None:
        self._exec("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

    def delete_user_sessions(self, user_id: int, *, except_hash: str | None = None) -> int:
        return self._exec("DELETE FROM sessions WHERE user_id = ? AND token_hash IS NOT ?", (user_id, except_hash))

    def user_sessions(self, user_id: int) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM sessions WHERE user_id = ?", (user_id,))

    def delete_expired_sessions(self, now: int) -> int:
        return self._exec("DELETE FROM sessions WHERE expires_at <= ?", (now,))

    # --- invites and password resets ---

    def add_token(self, token_hash: str, kind: str, *, now: int, expires_at: int, user_id: int | None = None,
                  email: str | None = None, quota_bytes: int | None = None) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO tokens (token_hash, kind, user_id, email, quota_bytes, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (token_hash, kind, user_id, email, quota_bytes, now, expires_at),
            )
            return int(cur.lastrowid or 0)

    def get_token(self, token_hash: str) -> dict[str, Any] | None:
        return self._one(
            "SELECT t.*, u.login AS user_login, u.email AS user_email FROM tokens t "
            "LEFT JOIN users u ON u.id = t.user_id WHERE t.token_hash = ?", (token_hash,))

    def get_token_by_id(self, token_id: int) -> dict[str, Any] | None:
        return self._one("SELECT * FROM tokens WHERE id = ?", (token_id,))

    def active_invites(self, now: int) -> list[dict[str, Any]]:
        return self._all(
            "SELECT * FROM tokens WHERE kind = 'invite' AND used_at IS NULL AND expires_at > ? "
            "ORDER BY created_at DESC, id DESC", (now,))

    def replace_invite(self, token_hash: str, *, email: str, quota_bytes: int | None, now: int,
                       expires_at: int) -> int | str:
        """A new invite for the email; an unused earlier one for the same address is deleted —
        inviting again is how a new link is issued. Returns the id or email_taken."""
        with self.transaction() as conn:
            if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
                return "email_taken"
            conn.execute("DELETE FROM tokens WHERE kind = 'invite' AND used_at IS NULL AND email = ?", (email,))
            cur = conn.execute(
                "INSERT INTO tokens (token_hash, kind, email, quota_bytes, created_at, expires_at) "
                "VALUES (?, 'invite', ?, ?, ?, ?)",
                (token_hash, email, quota_bytes, now, expires_at),
            )
            return int(cur.lastrowid or 0)

    def renew_invite(self, token_id: int, token_hash: str, *, expires_at: int) -> str | None:
        """A new token and expiry for an unused invite (expired ones too) — the old link stops
        working. Returns a refusal code (not_found, email_taken) or None."""
        with self.transaction() as conn:
            row = conn.execute("SELECT email FROM tokens WHERE id = ? AND kind = 'invite' AND used_at IS NULL",
                               (token_id,)).fetchone()
            if row is None or not row["email"]:
                return "not_found"
            if conn.execute("SELECT 1 FROM users WHERE email = ?", (row["email"],)).fetchone():
                return "email_taken"
            conn.execute("UPDATE tokens SET token_hash = ?, expires_at = ? WHERE id = ?",
                         (token_hash, expires_at, token_id))
            return None

    def delete_invite(self, token_id: int) -> bool:
        return self._exec("DELETE FROM tokens WHERE id = ? AND kind = 'invite' AND used_at IS NULL", (token_id,)) > 0

    def delete_tokens_expired_before(self, ts: int) -> int:
        return self._exec("DELETE FROM tokens WHERE expires_at <= ?", (ts,))

    def accept_invite(self, token_hash: str, now: int, *, login: str, password_hash: str) -> int | str:
        """One transaction: check the invite, email and login, create the user, mark the invite used.
        The email comes from the invite. Returns the user id or a refusal code: not_found, expired,
        email_taken, login_taken."""
        with self.transaction() as conn:
            row = conn.execute("SELECT * FROM tokens WHERE token_hash = ? AND kind = 'invite'",
                               (token_hash,)).fetchone()
            if row is None or not row["email"]:
                return "not_found"
            if row["used_at"] is not None or row["expires_at"] <= now:
                return "expired"
            if conn.execute("SELECT 1 FROM users WHERE email = ?", (row["email"],)).fetchone():
                return "email_taken"
            if conn.execute("SELECT 1 FROM users WHERE login = ?", (login,)).fetchone():
                return "login_taken"
            uid = self._insert_user(conn, login, row["email"], password_hash, "user", row["quota_bytes"], now)
            # BEGIN IMMEDIATE already serializes; used_at IS NULL is a second guard against a race
            if conn.execute("UPDATE tokens SET used_at = ?, user_id = ? WHERE id = ? AND used_at IS NULL",
                            (now, uid, row["id"])).rowcount != 1:
                raise RuntimeError("invite was used concurrently")
            return uid

    def accept_reset(self, token_hash: str, now: int, *, password_hash: str) -> int | str:
        """A new password via a reset link; all of the user's sessions are revoked."""
        with self.transaction() as conn:
            row = conn.execute("SELECT * FROM tokens WHERE token_hash = ? AND kind = 'reset'",
                               (token_hash,)).fetchone()
            if row is None or row["user_id"] is None:
                return "not_found"
            if row["used_at"] is not None or row["expires_at"] <= now:
                return "expired"
            if conn.execute("UPDATE tokens SET used_at = ? WHERE id = ? AND used_at IS NULL",
                            (now, row["id"])).rowcount != 1:
                return "expired"
            uid = row["user_id"]
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, uid))
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))
            return int(uid)

    # --- shares ---

    def create_share(self, slug: str, *, owner_id: int, title: str | None, expires_at: int | None,
                     password_hash: str | None, created_at: int) -> None:
        self._exec(
            "INSERT INTO shares (slug, owner_id, title, created_at, expires_at, password_hash) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (slug, owner_id, title, created_at, expires_at, password_hash),
        )

    def get_share(self, slug: str) -> dict[str, Any] | None:
        """The share plus `owner_blocked_at`: shares of a blocked owner do not open."""
        return self._one(
            "SELECT s.*, u.blocked_at AS owner_blocked_at FROM shares s "
            "LEFT JOIN users u ON u.id = s.owner_id WHERE s.slug = ?", (slug,))

    def share_summary(self, slug: str) -> dict[str, Any] | None:
        return self._one(SHARE_AGGREGATES + " WHERE s.slug = ?", (slug,))

    def list_shares(self, owner_id: int) -> list[dict[str, Any]]:
        return self._all(SHARE_AGGREGATES + " WHERE s.owner_id = ? ORDER BY s.created_at DESC, s.rowid DESC",
                         (owner_id,))

    def update_share(self, slug: str, **fields: Any) -> None:
        unknown = set(fields) - SHARE_FIELDS
        if unknown:
            raise ValueError(f"unknown share fields: {unknown}")
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        self._exec(f"UPDATE shares SET {cols} WHERE slug = ?", (*fields.values(), slug))

    def delete_share(self, slug: str) -> list[str]:
        """Deletes the share with its file and event rows; returns file ids to remove from disk."""
        with self.transaction() as conn:
            ids = [r[0] for r in conn.execute("SELECT id FROM files WHERE share_slug = ?", (slug,))]
            conn.execute("DELETE FROM shares WHERE slug = ?", (slug,))
        return ids

    def shares_expired_before(self, ts: int) -> list[str]:
        rows = self._all("SELECT slug FROM shares WHERE expires_at IS NOT NULL AND expires_at <= ?", (ts,))
        return [r["slug"] for r in rows]

    def empty_shares_created_before(self, ts: int) -> list[str]:
        rows = self._all(
            "SELECT slug FROM shares s WHERE s.created_at <= ? "
            "AND NOT EXISTS (SELECT 1 FROM files f WHERE f.share_slug = s.slug)",
            (ts,),
        )
        return [r["slug"] for r in rows]

    # --- files ---

    def add_file(self, *, file_id: str, share_slug: str, name: str, size: int, mime: str, kind: str,
                 created_at: int, last_modified: int | None) -> None:
        with self.transaction() as conn:
            pos = conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM files WHERE share_slug = ?", (share_slug,)
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO files (id, share_slug, name, size, mime, kind, status, position, created_at, last_modified) "
                "VALUES (?, ?, ?, ?, ?, ?, 'uploading', ?, ?, ?)",
                (file_id, share_slug, name, size, mime, kind, pos, created_at, last_modified),
            )

    def get_file(self, file_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM files WHERE id = ?", (file_id,))

    def share_files(self, slug: str) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM files WHERE share_slug = ? ORDER BY position", (slug,))

    def ready_files(self, slug: str) -> list[dict[str, Any]]:
        """What the recipient sees: unfinished uploads are not shown at all."""
        return self._all("SELECT * FROM files WHERE share_slug = ? AND status = 'ready' ORDER BY position", (slug,))

    def update_file(self, file_id: str, **fields: Any) -> None:
        unknown = set(fields) - FILE_FIELDS
        if unknown:
            raise ValueError(f"unknown file fields: {unknown}")
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        self._exec(f"UPDATE files SET {cols} WHERE id = ?", (*fields.values(), file_id))

    def delete_file(self, file_id: str) -> bool:
        return self._exec("DELETE FROM files WHERE id = ?", (file_id,)) > 0

    def uploading_files(self) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM files WHERE status = 'uploading'")

    def next_pending_media(self) -> dict[str, Any] | None:
        return self._one(
            "SELECT * FROM files WHERE media_status = 'pending' AND status = 'ready' "
            "ORDER BY completed_at, rowid LIMIT 1"
        )

    def all_file_ids(self) -> set[str]:
        return {r["id"] for r in self._all("SELECT id FROM files")}

    # --- events and counters ---

    def recent_event_exists(self, slug: str, kind: str, ip: str, since: int) -> bool:
        return self._one(
            "SELECT 1 FROM events WHERE share_slug = ? AND kind = ? AND ip = ? AND ts > ? LIMIT 1",
            (slug, kind, ip, since),
        ) is not None

    def add_event(self, slug: str, kind: str, *, ts: int, file_id: str | None, ip: str | None,
                  user_agent: str | None) -> None:
        counter = COUNTERS[kind]
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO events (share_slug, ts, kind, file_id, ip, user_agent) VALUES (?, ?, ?, ?, ?, ?)",
                (slug, ts, kind, file_id, ip, user_agent),
            )
            conn.execute(
                f"UPDATE shares SET {counter} = {counter} + 1, last_access_at = ? WHERE slug = ?", (ts, slug)
            )

    def events(self, slug: str, limit: int = 200) -> list[dict[str, Any]]:
        return self._all(
            "SELECT e.ts, e.kind, e.file_id, f.name AS file_name, e.ip, e.user_agent "
            "FROM events e LEFT JOIN files f ON f.id = e.file_id "
            "WHERE e.share_slug = ? ORDER BY e.ts DESC, e.id DESC LIMIT ?",
            (slug, limit),
        )
