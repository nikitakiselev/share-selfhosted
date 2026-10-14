"""Accounts: emails and usernames, passwords, sessions, invites and password resets.

The DB stores only sha256 of session and link tokens: a leaked database lets nobody
sign in or use someone else's invite.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from typing import Any

from share_app.db import Database
from share_app.errors import ApiError

SESSION_COOKIE = "share_session"
SESSION_TTL = 30 * 86400
INVITE_TTL = 7 * 86400
RESET_TTL = 86400
# last_seen_at is written no more often than this: otherwise every player Range request is a DB write
TOUCH_EVERY = 300

LOGIN_MIN, LOGIN_MAX = 3, 32
LOGIN_RE = re.compile(rf"^[a-z0-9._-]{{{LOGIN_MIN},{LOGIN_MAX}}}$")
# users sign in by email; no mail is sent, so the check is "looks like an address", nothing more
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
EMAIL_MAX = 254
PASSWORD_MIN, PASSWORD_MAX = 10, 200


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalize_login(raw: object) -> str:
    if not isinstance(raw, str):
        raise ApiError(400, "bad_login", "Username must be a string", min_length=LOGIN_MIN, max_length=LOGIN_MAX)
    login = raw.strip().lower()
    if not LOGIN_RE.match(login):
        raise ApiError(400, "bad_login", f"Username: {LOGIN_MIN} to {LOGIN_MAX} characters — latin letters, digits, "
                       "dot, hyphen, underscore", min_length=LOGIN_MIN, max_length=LOGIN_MAX)
    return login


def is_email(value: str) -> bool:
    return len(value) <= EMAIL_MAX and EMAIL_RE.match(value) is not None


def normalize_email(raw: object) -> str:
    email = raw.strip().lower() if isinstance(raw, str) else ""
    if not is_email(email):
        raise ApiError(400, "bad_email", "Invalid email")
    return email


def check_password(raw: object) -> str:
    if not isinstance(raw, str) or len(raw) < PASSWORD_MIN:
        raise ApiError(400, "weak_password", f"Password must be at least {PASSWORD_MIN} characters",
                       min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)
    if len(raw) > PASSWORD_MAX:
        raise ApiError(400, "weak_password", f"Password must be at most {PASSWORD_MAX} characters",
                       min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)
    return raw


# --- sessions ---

def create_session(db: Database, user_id: int, now: int, ip: str | None, ua: str | None) -> str:
    token = secrets.token_urlsafe(32)
    db.add_session(token_hash(token), user_id, now=now, expires_at=now + SESSION_TTL, ip=ip,
                   user_agent=(ua or "")[:500] or None)
    return token


def session_user(db: Database, token: str | None, now: int) -> dict[str, Any] | None:
    """The user behind a cookie. No session, expired, or blocked user — None."""
    if not token:
        return None
    user = db.session_user(token_hash(token))
    if user is None or user["session_expires_at"] <= now or user["blocked_at"] is not None:
        return None
    if now - user["session_last_seen_at"] >= TOUCH_EVERY:
        db.touch_session(user["session_hash"], now)
    return user


def revoke_sessions(db: Database, user_id: int, *, except_token: str | None = None) -> None:
    db.delete_user_sessions(user_id, except_hash=token_hash(except_token) if except_token else None)


# --- invites and resets ---

def new_token() -> str:
    return secrets.token_urlsafe(24)


def create_token(db: Database, kind: str, now: int, *, user_id: int | None = None, email: str | None = None,
                 quota_bytes: int | None = None) -> tuple[str, dict[str, Any]]:
    token = new_token()
    ttl = INVITE_TTL if kind == "invite" else RESET_TTL
    token_id = db.add_token(token_hash(token), kind, now=now, expires_at=now + ttl, user_id=user_id, email=email,
                            quota_bytes=quota_bytes)
    row = db.get_token_by_id(token_id)
    assert row is not None
    return token, row


def peek_token(db: Database, token: str, now: int) -> dict[str, Any]:
    row = db.get_token(token_hash(token))
    # an invite without an email (v2 leftovers) cannot be used — treat it as missing
    if row is None or (row["kind"] == "reset" and row["user_id"] is None) or (
            row["kind"] == "invite" and not row["email"]):
        raise ApiError(404, "not_found", "Link not found")
    if row["used_at"] is not None or row["expires_at"] <= now:
        raise ApiError(410, "token_expired", "The link has already been used or has expired")
    return row


TOKEN_ERRORS = {
    "not_found": (404, "Link not found"),
    "expired": (410, "The link has already been used or has expired"),
    "login_taken": (409, "This username is already taken"),
    "email_taken": (409, "This email is already registered"),
}


def token_error(code: str) -> ApiError:
    status, message = TOKEN_ERRORS[code]
    return ApiError(status, "token_expired" if code == "expired" else code, message)
