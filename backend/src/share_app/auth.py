"""Client IP, internal network, password hashes, signed link-password cookies, attempt limits."""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import secrets
from collections import deque
from collections.abc import Iterable

from share_app.config import IPNetwork

UNLOCK_TTL = 7 * 86400

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1


def unlock_cookie_name(slug: str) -> str:
    return f"share_unlock_{slug}"


# --- passwords ---

def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def verify_password(password: str, encoded: str | None) -> bool:
    """A broken or empty hash is always False, not an exception: it cannot be used to log in."""
    if not encoded:
        return False
    try:
        scheme, n, r, p, salt_b64, hash_b64 = encoded.split("$")
        if scheme != "scrypt":
            return False
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(hash_b64)
        digest = hashlib.scrypt(
            password.encode(), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected),
            maxmem=128 * int(r) * int(n) * 2,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)


# --- signed tokens ---

def _sign(secret: bytes, payload: str) -> str:
    return hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()


def make_unlock_token(secret: bytes, slug: str, version: int, now: int) -> str:
    exp = now + UNLOCK_TTL
    return f"{version}.{exp}.{_sign(secret, f'unlock|{slug}|{version}|{exp}')}"


def check_unlock_token(secret: bytes, token: str | None, slug: str, version: int, now: int) -> bool:
    """The token is bound to the password version: changing or removing the password voids it."""
    if not token:
        return False
    parts = token.split(".")
    if len(parts) != 3 or not parts[0].isdigit() or not parts[1].isdigit():
        return False
    ver, exp, sig = int(parts[0]), int(parts[1]), parts[2]
    if ver != version or exp <= now:
        return False
    return hmac.compare_digest(sig, _sign(secret, f"unlock|{slug}|{ver}|{exp}"))


# --- network ---

def client_ip(peer: str | None, forwarded_for: str | None, trusted_proxies: Iterable[IPNetwork]) -> str:
    """Client IP.

    `X-Forwarded-For` is honoured only if the TCP peer is a trusted proxy; from anyone else
    the header is ignored, otherwise anybody could forge it. Each proxy appends the address
    of whoever connected to it, so the chain is read from the right: trusted proxies are
    skipped and the first untrusted address is the client. Whatever a visitor puts in the
    header themselves stays to the left of their real address. If the whole chain is
    trusted, the client is the leftmost entry (a LAN visitor coming through the proxy).
    """
    trusted = tuple(trusted_proxies)
    peer = _normalize(peer or "")
    if not forwarded_for or not in_nets(peer, trusted):
        return peer
    chain = [_normalize(x) for x in forwarded_for.split(",") if x.strip()]
    for ip in reversed(chain):
        if not in_nets(ip, trusted):
            return ip
    return chain[0] if chain else peer


def _normalize(ip: str) -> str:
    try:
        addr = ipaddress.ip_address(ip.strip())
    except ValueError:
        return ip.strip()
    # IPv4 arriving via an IPv6 socket: ::ffff:192.168.1.10 → 192.168.1.10
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return str(addr)


def in_nets(ip: str, nets: Iterable[IPNetwork]) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in nets)


is_internal = in_nets


# --- attempt limiting ---

class RateLimiter:
    """At most `limit` failures per key within `window` seconds. State lives in process memory."""

    def __init__(self, limit: int, window: int) -> None:
        self.limit = limit
        self.window = window
        self._hits: dict[str, deque[int]] = {}

    def _prune(self, key: str, now: int) -> deque[int]:
        hits = self._hits.get(key)
        if hits is None:
            return deque()
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if not hits:
            del self._hits[key]
        return hits

    def blocked(self, key: str, now: int) -> bool:
        return len(self._prune(key, now)) >= self.limit

    def hit(self, key: str, now: int) -> None:
        self._prune(key, now)
        self._hits.setdefault(key, deque()).append(now)

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)
