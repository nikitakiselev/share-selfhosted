"""The first line of defence inside the app, independent of the reverse proxy.

Determines the client IP, keeps outsiders away from user management and checks Origin
on state-changing API requests. Plain ASGI, no BaseHTTPMiddleware: upload bodies are
streamed and must not be buffered anywhere.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.requests import cookie_parser
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from share_app import auth
from share_app.accounts import SESSION_COOKIE
from share_app.config import Settings

ADMIN_PREFIX = "/api/admin"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def is_admin_path(path: str) -> bool:
    return path == ADMIN_PREFIX or path.startswith(ADMIN_PREFIX + "/")


def origin_ok(origin: str, host: str | None, public_url: str) -> bool:
    try:
        parts = urlsplit(origin)
    except ValueError:
        return False
    if not parts.scheme or not parts.netloc:
        return False
    public = urlsplit(public_url)
    if (parts.scheme, parts.netloc) == (public.scheme, public.netloc):
        return True
    # the same host as in the request: local runs and access by IP
    return bool(host) and parts.netloc == host


def _deny(code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": code, "message": message}, status_code=403)


class AccessMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        client = scope.get("client")
        ip = auth.client_ip(client[0] if client else None, headers.get("x-forwarded-for"),
                            self.settings.trusted_proxies)
        scope.setdefault("state", {})["client_ip"] = ip
        path = scope["path"]

        if is_admin_path(path) and not auth.is_internal(ip, self.settings.internal_nets):
            await _deny("forbidden", "Available only from the internal network")(scope, receive, send)
            return

        if scope["method"] not in SAFE_METHODS and path.startswith("/api/"):
            origin = headers.get("origin")
            # with a session Origin is required: SameSite=Lax does not cover subdomains
            # or old browsers; without a session nothing can be changed, so only check one if sent
            has_session = SESSION_COOKIE in cookie_parser(headers.get("cookie", ""))
            if (origin is None and has_session) or (
                    origin is not None and not origin_ok(origin, headers.get("host"), self.settings.public_url)):
                await _deny("bad_origin", "Cross-site request")(scope, receive, send)
                return

        await self.app(scope, receive, send)
