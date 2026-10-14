"""DB rows → API JSON. The response shape is fixed in the spec; the frontend relies on it."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

# these segments are taken by service routes next to /files/{id}/{name}
RESERVED_SEGMENTS = {"play", "poster.jpg", "played"}


def is_expired(share: dict[str, Any], now: int) -> bool:
    return share["expires_at"] is not None and share["expires_at"] <= now


UNTITLED = {"en": "Untitled", "ru": "Без названия"}


def display_title(share: dict[str, Any], first_name: str | None, lang: str = "en") -> str:
    return share["title"] or first_name or UNTITLED[lang]


def file_base(slug: str, file_id: str) -> str:
    return f"/api/public/shares/{slug}/files/{file_id}"


def public_file(slug: str, f: dict[str, Any]) -> dict[str, Any]:
    base = file_base(slug, f["id"])
    segment = quote(f["name"], safe="")
    if segment in RESERVED_SEGMENTS:
        segment = "file-" + segment
    ready = f["status"] == "ready"
    url = f"{base}/{segment}" if ready else None
    playable_now = ready and f["media_status"] == "done" and f["play"] != "none"
    return {
        "id": f["id"],
        "name": f["name"],
        "size": f["size"],
        "mime": f["mime"],
        "kind": f["kind"],
        "status": f["status"],
        "media_status": f["media_status"],
        "playable": f["playable"],
        "duration": f["duration"],
        "width": f["width"],
        "height": f["height"],
        "url": url,
        "download_url": f"{url}?download=1" if url else None,
        "play_url": f"{base}/play" if playable_now else None,
        "poster_url": f"{base}/poster.jpg" if ready and f["has_poster"] else None,
    }


def admin_file(slug: str, f: dict[str, Any], uploaded: int) -> dict[str, Any]:
    return {
        **public_file(slug, f),
        "uploaded": uploaded,
        "play": f["play"],
        "video_codec": f["video_codec"],
        "audio_codec": f["audio_codec"],
        "created_at": f["created_at"],
        "completed_at": f["completed_at"],
    }


def admin_summary(row: dict[str, Any], url: str, now: int, lang: str = "en") -> dict[str, Any]:
    return {
        "slug": row["slug"],
        "url": url,
        "title": row["title"],
        "display_title": display_title(row, row.get("first_name"), lang),
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "expired": is_expired(row, now),
        "protected": row["password_hash"] is not None,
        "file_count": row["file_count"],
        "total_size": row["total_size"],
        "uploading_count": row["uploading_count"],
        "views": row["views"],
        "downloads": row["downloads"],
        "plays": row["plays"],
        "last_access_at": row["last_access_at"],
    }
