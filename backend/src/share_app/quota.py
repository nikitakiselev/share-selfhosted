"""A user's storage limit and used space.

The limit is `users.quota_bytes` and is permanent: the admin sets it, NULL means unlimited.
New users get it from their invite (SHARE_DEFAULT_QUOTA_GB by default).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from share_app.db import Database
    from share_app.storage import Disk

GiB = 1 << 30


def usage(db: Database, user: dict[str, Any], *, disk: Disk | None = None) -> dict[str, Any]:
    quota = user["quota_bytes"]
    used = db.used_bytes(user["id"])
    return {
        "quota": quota,
        "used": used,
        "free": None if quota is None else max(0, quota - used),
        "disk": {"used": disk.used, "total": disk.total, "free": disk.free}
        if disk is not None and user["role"] == "admin" else None,
    }
