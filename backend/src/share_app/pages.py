"""SPA pages and frontend static files.

There is one `index.html` for the whole app; for `/s/{slug}` a title and OG tags are put
into the `<!--og-->` marker so messengers show a proper link preview. Everything a guest
gets in HTML is in `settings.language`: crawlers do not send Accept-Language.
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response

from share_app import clock
from share_app.context import Context
from share_app.errors import not_found
from share_app.fmt import human_size, plural
from share_app.serialize import display_title, file_base, is_expired

OG_MARKER = "<!--og-->"
FALLBACK_INDEX = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1">'
    f"{OG_MARKER}</head><body><p>The frontend is not built: no index.html in SHARE_STATIC_DIR.</p></body></html>"
)
ROBOTS = '<meta name="robots" content="noindex, nofollow">'
HTML_TAG = re.compile(r"<html\b[^>]*>", re.IGNORECASE)
LANG_ATTR = re.compile(r"""\slang=(["']).*?\1""", re.IGNORECASE)

TEXTS = {
    "en": {
        "kinds": {"video": "Video", "audio": "Audio", "image": "Image", "other": "File"},
        "files": ("file", "files"),
        "unavailable": "Link unavailable",
        "protected_title": "Password-protected files",
        "protected_desc": "Open the link and enter the password",
        "uploading": "Files are uploading",
    },
    "ru": {
        "kinds": {"video": "Видео", "audio": "Аудио", "image": "Изображение", "other": "Файл"},
        "files": ("файл", "файла", "файлов"),
        "unavailable": "Ссылка недоступна",
        "protected_title": "Файлы под паролем",
        "protected_desc": "Откройте ссылку и введите пароль",
        "uploading": "Файлы загружаются",
    },
}

_cache: dict[Path, tuple[int, str]] = {}


def _ctx(request: Request) -> Context:
    return request.app.state.ctx


def load_index(static_dir: Path) -> str:
    path = static_dir / "index.html"
    try:
        mtime = path.stat().st_mtime_ns
    except FileNotFoundError:
        return FALLBACK_INDEX
    cached = _cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    text = path.read_text(encoding="utf-8")
    _cache[path] = (mtime, text)
    return text


def set_lang(template: str, lang: str) -> str:
    """Put `lang` on the <html> tag, replacing whatever the build had there."""
    def fix(m: re.Match[str]) -> str:
        tag = LANG_ATTR.sub("", m.group(0))
        return f'{tag[:5]} lang="{lang}"{tag[5:]}'
    return HTML_TAG.sub(fix, template, count=1)


def render(template: str, head: str, lang: str = "en") -> str:
    template = set_lang(template, lang)
    if OG_MARKER in template:
        return template.replace(OG_MARKER, head, 1)
    return template.replace("</head>", head + "</head>", 1)


def _meta(prop: str, content: str, attr: str = "property") -> str:
    return f'<meta {attr}="{prop}" content="{html.escape(content, quote=True)}">'


def default_head() -> str:
    return f"<title>Share</title>{ROBOTS}"


def describe(files: list[dict[str, Any]], lang: str = "en") -> str:
    texts = TEXTS[lang]
    total = human_size(sum(f["size"] for f in files), lang)
    if len(files) == 1:
        kinds = texts["kinds"]
        return f"{kinds.get(files[0]['kind'], kinds['other'])} · {total}"
    n = len(files)
    return f"{n} {plural(n, lang, texts['files'])} · {total}"


def share_head(ctx: Context, slug: str) -> str:
    lang = ctx.settings.language
    texts = TEXTS[lang]
    share = ctx.db.get_share(slug)
    url = ctx.share_url(slug)
    if share is None or share["owner_blocked_at"] is not None or is_expired(share, clock.now()):
        title, desc, image = "Share", texts["unavailable"], None
    elif share["password_hash"] is not None:
        # password-protected — no title, no file names, no picture
        title, desc, image = texts["protected_title"], texts["protected_desc"], None
    else:
        files = ctx.db.ready_files(slug)
        title = display_title(share, files[0]["name"] if files else None, lang)
        desc = describe(files, lang) if files else texts["uploading"]
        with_poster = next((f for f in files if f["has_poster"]), None)
        image = (f"{ctx.settings.public_url}{file_base(slug, with_poster['id'])}/poster.jpg"
                 if with_poster else None)
    parts = [
        f"<title>{html.escape(title)}</title>",
        ROBOTS,
        _meta("og:type", "website"),
        _meta("og:site_name", "Share"),
        _meta("og:title", title),
        _meta("og:description", desc),
        _meta("og:url", url),
        _meta("twitter:card", "summary_large_image" if image else "summary", attr="name"),
    ]
    if image:
        parts.append(_meta("og:image", image))
    return "".join(parts)


def _html(text: str) -> HTMLResponse:
    return HTMLResponse(text, headers={"Cache-Control": "no-cache"})


async def spa(request: Request) -> Response:
    settings = _ctx(request).settings
    return _html(render(load_index(settings.static_dir), default_head(), settings.language))


async def share_page(request: Request) -> Response:
    ctx = _ctx(request)
    head = share_head(ctx, request.path_params["slug"])
    return _html(render(load_index(ctx.settings.static_dir), head, ctx.settings.language))


async def asset(request: Request) -> Response:
    base = (_ctx(request).settings.static_dir / "assets").resolve()
    target = (base / request.path_params["path"]).resolve()
    if not target.is_relative_to(base) or not target.is_file():
        raise not_found()
    return FileResponse(target, headers={"Cache-Control": "public, max-age=31536000, immutable"})


async def favicon(request: Request) -> Response:
    target = _ctx(request).settings.static_dir / "favicon.svg"
    if not target.is_file():
        raise not_found()
    return FileResponse(target, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})


async def healthz(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})
