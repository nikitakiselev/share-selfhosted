"""Application assembly: routes, middleware, background tasks, the first admin."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.routing import Route

from share_app import (
    accounts,
    admin,
    app_api,
    auth_api,
    cleanup,
    clock,
    pages,
    public,
    tus,
)
from share_app.access import AccessMiddleware
from share_app.auth import hash_password
from share_app.config import Settings
from share_app.context import Context
from share_app.db import Database
from share_app.errors import ApiError, api_error_handler, http_error_handler
from share_app.media import MediaWorker
from share_app.storage import Storage

PUB = "/api/public/shares/{slug}"
FILE = PUB + "/files/{file_id}"
AUTH = "/api/auth"
APP = "/api/app"
ADM = "/api/admin"

log = logging.getLogger("share")


def routes() -> list[Route]:
    return [
        Route("/healthz", pages.healthz),
        # public
        Route(PUB, public.share_card),
        Route(PUB + "/unlock", public.unlock, methods=["POST"]),
        Route(PUB + "/zip", public.share_zip),
        # service segments before {name}: "play"/"poster.jpg" never appear as a file name
        # in URLs — serialize renames such a segment
        Route(FILE + "/play", public.file_play),
        Route(FILE + "/poster.jpg", public.file_poster),
        Route(FILE + "/played", public.file_played, methods=["POST"]),
        Route(FILE + "/{name:path}", public.file_original),
        # sign-in and account
        Route(AUTH + "/session", auth_api.session),
        Route(AUTH + "/login", auth_api.login, methods=["POST"]),
        Route(AUTH + "/logout", auth_api.logout, methods=["POST"]),
        Route(AUTH + "/logout-all", auth_api.logout_all, methods=["POST"]),
        Route(AUTH + "/password", auth_api.change_password, methods=["POST"]),
        Route(AUTH + "/tokens/{token}", auth_api.token_info),
        Route(AUTH + "/tokens/{token}", auth_api.token_accept, methods=["POST"]),
        # own shares and files
        Route(APP + "/usage", app_api.usage),
        Route(APP + "/shares", app_api.list_shares),
        Route(APP + "/shares", app_api.create_share, methods=["POST"]),
        Route(APP + "/shares/{slug}", app_api.get_share),
        Route(APP + "/shares/{slug}", app_api.patch_share, methods=["PATCH"]),
        Route(APP + "/shares/{slug}", app_api.delete_share, methods=["DELETE"]),
        Route(APP + "/shares/{slug}/files/{file_id}", app_api.patch_file, methods=["PATCH"]),
        Route(APP + "/shares/{slug}/files/{file_id}", app_api.delete_file, methods=["DELETE"]),
        Route(APP + "/tus/", tus.options, methods=["OPTIONS"]),
        Route(APP + "/tus/", tus.create, methods=["POST"]),
        Route(APP + "/tus", tus.options, methods=["OPTIONS"]),
        Route(APP + "/tus", tus.create, methods=["POST"]),
        Route(APP + "/tus/{file_id}", tus.resource, methods=["HEAD", "PATCH", "DELETE", "OPTIONS"]),
        # users and invites — admin from internal networks
        Route(ADM + "/users", admin.list_users),
        Route(ADM + "/users/{user_id:int}", admin.patch_user, methods=["PATCH"]),
        Route(ADM + "/users/{user_id:int}", admin.delete_user, methods=["DELETE"]),
        Route(ADM + "/users/{user_id:int}/reset", admin.reset_link, methods=["POST"]),
        Route(ADM + "/invites", admin.list_invites),
        Route(ADM + "/invites", admin.create_invite, methods=["POST"]),
        Route(ADM + "/invites/{invite_id:int}", admin.delete_invite, methods=["DELETE"]),
        Route(ADM + "/invites/{invite_id:int}/renew", admin.renew_invite, methods=["POST"]),
        # pages and static files
        Route("/", pages.spa),
        Route("/shares", pages.spa),
        Route("/shares/{slug}", pages.spa),
        Route("/users", pages.spa),
        Route("/invite/{token}", pages.spa),
        Route("/reset/{token}", pages.spa),
        Route("/s/{slug}", pages.share_page),
        Route("/assets/{path:path}", pages.asset),
        Route("/favicon.svg", pages.favicon),
    ]


def admin_login(email: str) -> str:
    """The first admin's username: the part of the email before @, fitted to the login rules."""
    login = re.sub(r"[^a-z0-9._-]", "-", email.split("@", 1)[0].lower()).strip("._-")[:32]
    return login if accounts.LOGIN_RE.match(login) else "admin"


def bootstrap_admin(db: Database, settings: Settings) -> None:
    """While there are no users, the first admin is created from SHARE_ADMIN_EMAIL and
    SHARE_ADMIN_PASSWORD. After that the password lives in the DB and the variables are ignored."""
    if db.count_users() > 0:
        if settings.admin_password:
            log.warning("SHARE_ADMIN_PASSWORD is ignored: users already exist, the variable can be removed")
        return
    if not settings.admin_email or not settings.admin_password:
        raise ValueError("there are no users yet: set SHARE_ADMIN_EMAIL and SHARE_ADMIN_PASSWORD "
                         "to create the first admin")
    try:
        password = accounts.check_password(settings.admin_password)
    except ApiError:
        raise ValueError(f"SHARE_ADMIN_PASSWORD must be {accounts.PASSWORD_MIN} to {accounts.PASSWORD_MAX} "
                         "characters long") from None
    login = admin_login(settings.admin_email)
    db.create_user(login=login, email=settings.admin_email, password_hash=hash_password(password), role="admin",
                   quota_bytes=None, created_at=clock.now())
    log.info("created the first admin %s <%s>", login, settings.admin_email)


def create_app(settings: Settings) -> Starlette:
    storage = Storage(settings.data_dir)
    storage.ensure_dirs()
    db = Database(storage.db_path)
    try:
        bootstrap_admin(db, settings)
    except BaseException:
        db.close()
        raise
    worker = MediaWorker(settings, db, storage)
    ctx = Context(settings=settings, db=db, storage=storage, worker=worker)

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        tasks: list[asyncio.Task] = []
        if settings.background:
            await anyio.to_thread.run_sync(cleanup.remove_orphans, ctx)
            worker.start()
            tasks.append(asyncio.create_task(cleanup.loop(ctx), name="cleanup"))
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            await worker.stop()

    app = Starlette(
        routes=routes(),
        middleware=[Middleware(AccessMiddleware, settings=settings)],
        exception_handlers={ApiError: api_error_handler, HTTPException: http_error_handler},
        lifespan=lifespan,
    )
    app.state.ctx = ctx
    return app
