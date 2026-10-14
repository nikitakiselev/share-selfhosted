"""The `share-app` entry point.

    share-app                                          — run the server (settings from the environment,
                                                         see config.py)
    share-app set-password --email <email>             — read a password from stdin and store it;
                                                         the user's sessions are revoked
    share-app set-email --email <email> --new-email <email>
                                                       — change a user's email (users sign in with it)
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # CLI imports are lazy
    from share_app.config import Settings
    from share_app.db import Database

USAGE = "usage: share-app [set-password --email <email> | set-email --email <email> --new-email <email>]"


def _open_db(settings: Settings) -> Database:
    from share_app.db import Database
    from share_app.storage import Storage

    storage = Storage(settings.data_dir)
    storage.ensure_dirs()
    return Database(storage.db_path)


def _set_password(email: str) -> int:
    from share_app import accounts
    from share_app.auth import hash_password
    from share_app.config import load_settings
    from share_app.errors import ApiError

    try:
        settings = load_settings()
        email = accounts.normalize_email(email)
        password = accounts.check_password(sys.stdin.readline().rstrip("\r\n"))
    except (ValueError, ApiError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    db = _open_db(settings)
    try:
        user = db.get_user_by_email(email)
        if user is None:
            print(f"no user with email {email}", file=sys.stderr)
            return 1
        db.update_user(user["id"], password_hash=hash_password(password))
        accounts.revoke_sessions(db, user["id"])
        print(f"password of {user['login']} updated, sessions revoked", file=sys.stderr)
        return 0
    finally:
        db.close()


def _set_email(email: str, new_email: str) -> int:
    from share_app import accounts
    from share_app.config import load_settings
    from share_app.errors import ApiError

    try:
        settings = load_settings()
        email = accounts.normalize_email(email)
        new_email = accounts.normalize_email(new_email)
    except (ValueError, ApiError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    db = _open_db(settings)
    try:
        user = db.get_user_by_email(email)
        if user is None:
            print(f"no user with email {email}", file=sys.stderr)
            return 1
        other = db.get_user_by_email(new_email)
        if other is not None and other["id"] != user["id"]:
            print(f"email {new_email} is already taken by {other['login']}", file=sys.stderr)
            return 1
        db.update_user(user["id"], email=new_email)
        print(f"email of {user['login']}: {new_email}", file=sys.stderr)
        return 0
    finally:
        db.close()


def _serve() -> int:
    import uvicorn

    from share_app.app import create_app
    from share_app.config import load_settings

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # own events at INFO; uvicorn only warnings and errors, and no access log:
    # the player's Range requests would flood it
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    try:
        settings = load_settings()
        app = create_app(settings)
    except (ValueError, RuntimeError) as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    logging.getLogger("share").info("share listening on %s:%d, data in %s", settings.host, settings.port,
                                    settings.data_dir)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        access_log=False,
        log_config=None,
        proxy_headers=False,  # X-Forwarded-For is parsed by us, trusting only SHARE_TRUSTED_PROXIES
        server_header=False,
        http="h11",
        loop="asyncio",
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) == 3 and args[:2] == ["set-password", "--email"]:
        return _set_password(args[2])
    if len(args) == 5 and args[:2] == ["set-email", "--email"] and args[3] == "--new-email":
        return _set_email(args[2], args[4])
    if args:
        print(USAGE, file=sys.stderr)
        return 2
    return _serve()


if __name__ == "__main__":
    sys.exit(main())
