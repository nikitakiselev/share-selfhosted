"""Application settings. The only place that reads the environment."""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from share_app.accounts import is_email
from share_app.quota import GiB

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

# private ranges: the admin area is reachable from the LAN and VPN out of the box
DEFAULT_INTERNAL_NETS = "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7"
# loopback is always internal: local runs and checks from inside the container
LOOPBACK_NETS = ("127.0.0.0/8", "::1/128")
# X-Forwarded-For is honoured from private networks and loopback: a reverse proxy on the same
# host (seen through the Docker gateway) or in the LAN works out of the box. Taking the
# rightmost untrusted address keeps it unforgeable from outside.
DEFAULT_TRUSTED_PROXIES = ",".join((DEFAULT_INTERNAL_NETS, *LOOPBACK_NETS))


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    static_dir: Path
    secret: bytes
    public_url: str
    # first admin: created on start while there are no users; afterwards the password lives in the DB
    admin_email: str | None = None
    admin_password: str | None = field(default=None, repr=False)
    # quota of new users (bytes) unless the invite sets its own; None — unlimited
    default_quota: int | None = GiB
    # X-Forwarded-For is trusted only from these addresses; empty — not trusted at all
    trusted_proxies: tuple[IPNetwork, ...] = ()
    internal_nets: tuple[IPNetwork, ...] = ()
    host: str = "0.0.0.0"
    port: int = 8000
    cookie_secure: bool = True
    # language of server-rendered pages and link previews (OG): crawlers send no Accept-Language
    language: str = "en"
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    # disk space that is never given to uploads
    disk_reserve: int = 1 << 30
    cleanup_interval: float = 600.0
    # media worker and cleanup; tests turn them off and run them by hand
    background: bool = True


def parse_nets(raw: str) -> tuple[IPNetwork, ...]:
    nets = [n.strip() for n in raw.split(",") if n.strip()]
    try:
        parsed = [ipaddress.ip_network(n, strict=False) for n in (*nets, *LOOPBACK_NETS)]
    except ValueError as exc:
        raise ValueError(f"SHARE_INTERNAL_NETS: {exc}") from None
    return tuple(parsed)


def parse_proxies(raw: str) -> tuple[IPNetwork, ...]:
    out = []
    for item in (p.strip() for p in raw.split(",")):
        if not item:
            continue
        try:
            out.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            raise ValueError(f"SHARE_TRUSTED_PROXIES: {item!r} is not an IP address or network") from None
    return tuple(out)


def parse_default_quota(raw: str) -> int | None:
    value = raw.strip().lower()
    if value == "unlimited":
        return None
    if not value.isdigit() or int(value) < 1:
        raise ValueError(f"SHARE_DEFAULT_QUOTA_GB: {raw!r} — expected a whole number of GiB (1 or more) "
                         "or unlimited")
    return int(value) * GiB


LANGUAGES = ("en", "ru")


def parse_language(raw: str) -> str:
    value = raw.strip().lower() or "en"
    if value not in LANGUAGES:
        raise ValueError(f"SHARE_LANGUAGE: {raw!r} — expected one of: {', '.join(LANGUAGES)}")
    return value


def parse_public_url(raw: str) -> str:
    url = raw.strip().rstrip("/")
    if not url:
        raise ValueError("SHARE_PUBLIC_URL is not set — the address users open, e.g. https://share.example.com")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(f"SHARE_PUBLIC_URL: {raw!r} — expected http(s)://host")
    return url


def _flag(raw: str) -> bool:
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    src = os.environ if env is None else env
    secret = src.get("SHARE_SECRET", "")
    if len(secret) < 16:
        raise ValueError("SHARE_SECRET is not set or shorter than 16 characters — the server does not start "
                         "without it")
    public_url = parse_public_url(src.get("SHARE_PUBLIC_URL", ""))
    try:
        port = int(src.get("SHARE_PORT", "8000"))
    except ValueError:
        raise ValueError("SHARE_PORT must be a number") from None
    admin_email = src.get("SHARE_ADMIN_EMAIL", "").strip().lower() or None
    if admin_email is not None and not is_email(admin_email):
        raise ValueError(f"SHARE_ADMIN_EMAIL: {admin_email!r} is not an email address")
    # Secure cookies follow the public scheme unless set explicitly
    cookie_secure = src.get("SHARE_COOKIE_SECURE", "").strip()
    return Settings(
        data_dir=Path(src.get("SHARE_DATA_DIR", "/data")),
        static_dir=Path(src.get("SHARE_STATIC_DIR", "/app/static")),
        secret=secret.encode(),
        public_url=public_url,
        admin_email=admin_email,
        admin_password=src.get("SHARE_ADMIN_PASSWORD") or None,
        default_quota=parse_default_quota(src.get("SHARE_DEFAULT_QUOTA_GB", "").strip() or "1"),
        trusted_proxies=parse_proxies(src.get("SHARE_TRUSTED_PROXIES", DEFAULT_TRUSTED_PROXIES)),
        internal_nets=parse_nets(src.get("SHARE_INTERNAL_NETS", DEFAULT_INTERNAL_NETS)),
        host=src.get("SHARE_HOST", "0.0.0.0"),
        port=port,
        cookie_secure=_flag(cookie_secure) if cookie_secure else public_url.startswith("https://"),
        language=parse_language(src.get("SHARE_LANGUAGE", "en")),
        ffmpeg=src.get("SHARE_FFMPEG", "ffmpeg"),
        ffprobe=src.get("SHARE_FFPROBE", "ffprobe"),
    )
