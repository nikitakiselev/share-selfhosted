from __future__ import annotations

from share_app import auth
from share_app.config import DEFAULT_TRUSTED_PROXIES, parse_nets, parse_proxies

NETS = parse_nets("192.168.1.0/24,10.8.0.0/24")
CADDY = parse_proxies("192.168.1.2")
PRIVATE = parse_proxies(DEFAULT_TRUSTED_PROXIES)


def test_password_roundtrip():
    h = auth.hash_password("секрет")
    assert h.startswith("scrypt$16384$8$1$")
    assert auth.verify_password("секрет", h)
    assert not auth.verify_password("секрет ", h)


def test_broken_hash_never_verifies():
    for bad in ("", None, "scrypt$x", "md5$1$2$3$4$5", "scrypt$16384$8$1$!!!$!!!"):
        assert not auth.verify_password("x", bad)


def test_xff_trusted_only_from_caddy():
    assert auth.client_ip("192.168.1.2", "1.2.3.4", CADDY) == "1.2.3.4"
    # a chain: only the last address is trusted — the proxy appended it
    assert auth.client_ip("192.168.1.2", "192.168.1.5, 1.2.3.4", CADDY) == "1.2.3.4"
    # not from the proxy — the header is ignored, an internal IP cannot be faked
    assert auth.client_ip("1.2.3.4", "192.168.1.5", CADDY) == "1.2.3.4"
    assert auth.client_ip("192.168.1.2", None, CADDY) == "192.168.1.2"


def test_xff_rightmost_untrusted_wins():
    # nginx appends to whatever the client sent: a forged internal address stays on the left
    assert auth.client_ip("192.168.1.2", "10.0.0.5, 203.0.113.9", PRIVATE) == "203.0.113.9"
    # a chain of trusted proxies is skipped from the right
    assert auth.client_ip("10.0.0.2", "203.0.113.9, 192.168.1.1", PRIVATE) == "203.0.113.9"
    # everyone in the chain is trusted — the client is the leftmost (a LAN visitor via the proxy)
    assert auth.client_ip("10.0.0.2", "192.168.1.5", PRIVATE) == "192.168.1.5"


def test_proxy_on_docker_host_by_default():
    """Proxy on the same host: the container sees the Docker gateway. With the default
    trusted networks the real client comes from X-Forwarded-For, so an internet visitor
    is not mistaken for an internal one."""
    nets = parse_nets("10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7")
    ip = auth.client_ip("172.17.0.1", "203.0.113.9", PRIVATE)
    assert ip == "203.0.113.9" and not auth.is_internal(ip, nets)


def test_ipv4_mapped_normalized():
    assert auth.client_ip("::ffff:192.168.1.10", None, CADDY) == "192.168.1.10"


def test_internal_nets():
    assert auth.is_internal("192.168.1.10", NETS)
    assert auth.is_internal("10.8.0.2", NETS)
    assert auth.is_internal("127.0.0.1", NETS)
    assert not auth.is_internal("203.0.113.5", NETS)
    assert not auth.is_internal("testclient", NETS)


def test_unlock_token_bound_to_slug_and_version():
    secret = b"k" * 32
    t = auth.make_unlock_token(secret, "abc", 3, 1000)
    assert auth.check_unlock_token(secret, t, "abc", 3, 1001)
    assert not auth.check_unlock_token(secret, t, "abd", 3, 1001)
    assert not auth.check_unlock_token(secret, t, "abc", 4, 1001)
    assert not auth.check_unlock_token(secret, t, "abc", 3, 1000 + auth.UNLOCK_TTL)
    assert not auth.check_unlock_token(secret, "garbage", "abc", 3, 1001)


def test_rate_limiter_window():
    rl = auth.RateLimiter(limit=2, window=60)
    assert not rl.blocked("k", 0)
    rl.hit("k", 0)
    rl.hit("k", 10)
    assert rl.blocked("k", 20)
    assert not rl.blocked("k", 61)  # the first attempt left the window
    rl.hit("k", 61)
    assert rl.blocked("k", 62)
    rl.reset("k")
    assert not rl.blocked("k", 62)
