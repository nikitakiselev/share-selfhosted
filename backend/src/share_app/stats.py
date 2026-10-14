"""Link statistics: views, downloads, plays.

Preview bots (Telegram, WhatsApp, Slack…) and the link owner (by session) are not counted.
curl and wget are counted — those are real downloads.
"""

from __future__ import annotations

import re
from typing import Any

from starlette.requests import Request

from share_app import clock
from share_app.context import Context

# "bot"/"crawler"/"spider" as a separate word or before / - _ ; plus previewers without these words.
# Plain "telegram" is not matched: Telegram's in-app browser on Android is a real person.
BOT_RE = re.compile(
    r"(bot|crawler|spider)\b|facebookexternalhit|whatsapp|vkshare|skypeuripreview|embedly|iframely|headlesschrome",
    re.IGNORECASE,
)
VIEW_DEDUP = 30 * 60


def is_bot(user_agent: str | None) -> bool:
    return bool(user_agent) and bool(BOT_RE.search(user_agent or ""))


def record(ctx: Context, request: Request, share: dict[str, Any], kind: str, file_id: str | None = None) -> bool:
    """Record the event if it should be counted. Returns whether it was recorded."""
    ua = request.headers.get("user-agent")
    if is_bot(ua) or ctx.is_owner(request, share):
        return False
    slug = share["slug"]
    ip = ctx.client_ip(request)
    now = clock.now()
    if kind == "view" and ctx.db.recent_event_exists(slug, "view", ip, now - VIEW_DEDUP):
        return False
    ctx.db.add_event(slug, kind, ts=now, file_id=file_id, ip=ip, user_agent=(ua or "")[:500] or None)
    return True
