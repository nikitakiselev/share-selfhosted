"""Shared application state and operations needed by several modules at once."""

from __future__ import annotations

import asyncio
import logging
import secrets
import string
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from starlette.requests import Request
from starlette.responses import Response

from share_app import accounts, auth, clock
from share_app.config import Settings
from share_app.db import Database
from share_app.errors import ApiError
from share_app.storage import Storage

if TYPE_CHECKING:
    from share_app.media import MediaWorker

log = logging.getLogger("share")

SLUG_ALPHABET = string.ascii_letters + string.digits
SLUG_LEN = 10
# "user not looked up yet" — distinct from "looked up, no session" (None)
_UNSET = object()


def new_slug() -> str:
    return "".join(secrets.choice(SLUG_ALPHABET) for _ in range(SLUG_LEN))


def new_file_id() -> str:
    """UUID7 (RFC 9562): 48 bits of milliseconds and 74 random bits — ids grow over time.
    uuid.uuid7 only appeared in Python 3.14, and we run on 3.12."""
    ms = time.time_ns() // 1_000_000
    rand = secrets.randbits(74)
    value = (ms << 80) | (0x7 << 76) | ((rand >> 62) << 64) | (0b10 << 62) | (rand & ((1 << 62) - 1))
    return str(uuid.UUID(int=value))


@dataclass
class Context:
    settings: Settings
    db: Database
    storage: Storage
    worker: MediaWorker
    # failed logins: per IP and per account (against brute force from many addresses)
    login_limiter: auth.RateLimiter = field(default_factory=lambda: auth.RateLimiter(5, 300))
    login_user_limiter: auth.RateLimiter = field(default_factory=lambda: auth.RateLimiter(10, 900))
    unlock_limiter: auth.RateLimiter = field(default_factory=lambda: auth.RateLimiter(10, 900))
    app_token_limiter: auth.RateLimiter = field(default_factory=lambda: auth.RateLimiter(10, 900))
    # pending desktop-app connect codes by token hash
    app_codes: dict[str, accounts.AppCode] = field(default_factory=dict)
    upload_locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    # --- request ---

    def client_ip(self, request: Request) -> str:
        return request.state.client_ip

    def is_internal(self, request: Request) -> bool:
        return auth.is_internal(self.client_ip(request), self.settings.internal_nets)

    def session_token(self, request: Request) -> str | None:
        """The browser sends the session in a cookie, the desktop app as `Authorization: Bearer`.
        A Bearer request carries no cookie, so the Origin check does not apply to it — and
        nothing can forge it from a web page."""
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() == "bearer":
            return token.strip() or None
        return request.cookies.get(accounts.SESSION_COOKIE)

    def current_user(self, request: Request) -> dict[str, Any] | None:
        """The session's user; looked up once per request, then taken from request.state."""
        cached = getattr(request.state, "user", _UNSET)
        if cached is _UNSET:
            cached = accounts.session_user(self.db, self.session_token(request), clock.now())
            request.state.user = cached
        return cached

    def require_user(self, request: Request) -> dict[str, Any]:
        user = self.current_user(request)
        if user is None:
            raise ApiError(401, "unauthenticated", "Sign in required")
        return user

    def require_admin_panel(self, request: Request) -> dict[str, Any]:
        """User management: the admin role AND an internal IP — a stolen admin session
        cannot reach it from outside."""
        user = self.require_user(request)
        if user["role"] != "admin" or not self.is_internal(request):
            raise ApiError(403, "forbidden", "Available only to an admin from the internal network")
        return user

    def own_share(self, request: Request, slug: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """The user's own link and the user. Someone else's link answers like a missing one."""
        user = self.require_user(request)
        share = self.db.get_share(slug)
        if share is None or share["owner_id"] != user["id"]:
            raise ApiError(404, "not_found", "Link not found")
        return share, user

    def is_owner(self, request: Request, share: dict[str, Any]) -> bool:
        user = self.current_user(request)
        return user is not None and user["id"] == share["owner_id"]

    def set_session_cookie(self, response: Response, token: str) -> None:
        response.set_cookie(
            accounts.SESSION_COOKIE, token, max_age=accounts.SESSION_TTL, path="/", httponly=True,
            secure=self.settings.cookie_secure, samesite="lax",
        )

    def clear_session_cookie(self, response: Response) -> None:
        response.delete_cookie(accounts.SESSION_COOKIE, path="/", httponly=True, secure=self.settings.cookie_secure,
                               samesite="lax")

    def share_url(self, slug: str) -> str:
        return f"{self.settings.public_url}/s/{slug}"

    # --- space ---

    def upload_capacity(self) -> int:
        """How much more can be accepted: free space minus the reserve minus unfinished upload tails."""
        pending = 0
        for f in self.db.uploading_files():
            offset = self.storage.upload_offset(f["id"]) or 0
            pending += max(0, f["size"] - offset)
        return max(0, self.storage.disk().free - self.settings.disk_reserve - pending)

    # --- deletion ---

    def delete_share(self, slug: str, *, reason: str) -> bool:
        share = self.db.get_share(slug)
        if share is None:
            return False
        ids = self.db.delete_share(slug)
        for fid in ids:
            self.worker.cancel(fid)
            self.storage.remove(fid)
        log.info("link %s deleted (%s), files: %d", slug, reason, len(ids))
        return True

    def delete_user(self, user: dict[str, Any], *, reason: str) -> int:
        ids = self.db.delete_user(user["id"])
        for fid in ids:
            self.worker.cancel(fid)
            self.storage.remove(fid)
        log.info("user %s deleted (%s), files: %d", user["login"], reason, len(ids))
        return len(ids)

    def delete_file(self, file: dict[str, Any], *, reason: str) -> None:
        self.db.delete_file(file["id"])
        self.worker.cancel(file["id"])
        self.storage.remove(file["id"])
        log.info("file %s/%s %r deleted (%s)", file["share_slug"], file["id"], file["name"], reason)
