from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from share_app.config import load_settings
from share_app.quota import GiB
from tests.conftest import new_share, tus_create, tus_patch, upload


def test_quota_exceeded(make_user, ctx):
    # quotas in bytes instead of gigabytes — testing arithmetic, not the disk
    user = make_user("carol", quota=1000)
    slug = new_share(user)["slug"]
    upload(user, slug, b"x" * 100)
    r = tus_create(user, slug, 901)
    assert r.status_code == 413
    assert r.json() == {
        "error": "quota_exceeded",
        "message": "Quota exceeded: need 901 B, free 900 B",
        "needed": 901,
        "free": 900,
    }
    assert len(ctx.db.share_files(slug)) == 1
    # exactly the remainder is fine, and an unfinished upload counts as used right away
    assert tus_create(user, slug, 900).status_code == 201
    r = tus_create(user, slug, 1)
    assert r.status_code == 413 and r.json()["free"] == 0
    u = user.get("/api/app/usage").json()
    assert (u["quota"], u["used"], u["free"]) == (1000, 1000, 0)


def test_resume_after_quota_lowered(make_user, ctx):
    user = make_user("payer", quota=2000)
    slug = new_share(user)["slug"]
    loc = tus_create(user, slug, 1500).headers["location"]
    assert tus_patch(user, loc, b"a" * 500, 0).status_code == 204
    ctx.db.update_user(user.user_id, quota_bytes=1000)
    u = user.get("/api/app/usage").json()
    assert u["quota"] == 1000 and u["used"] == 1500 and u["free"] == 0
    # a started upload completes, a new one does not start
    assert tus_patch(user, loc, b"b" * 1000, 500).status_code == 204
    fid = loc.rsplit("/", 1)[1]
    assert ctx.db.get_file(fid)["status"] == "ready"
    r = tus_create(user, slug, 1)
    assert r.status_code == 413 and r.json()["error"] == "quota_exceeded"


def test_unlimited_user(make_user):
    user = make_user("dave", quota=None)
    slug = new_share(user)["slug"]
    assert tus_create(user, slug, 10_000).status_code == 201
    u = user.get("/api/app/usage").json()
    assert u == {"quota": None, "used": 10_000, "free": None, "disk": None}


def test_admin_has_no_quota(admin: TestClient):
    slug = new_share(admin)["slug"]
    upload(admin, slug, b"x" * 5000)
    assert tus_create(admin, slug, 10_000).status_code == 201
    u = admin.get("/api/app/usage").json()
    assert u["quota"] is None and u["free"] is None and u["used"] == 15_000


def test_limited_admin(admin: TestClient, ctx):
    ctx.db.update_user(admin.user_id, quota_bytes=100)
    slug = new_share(admin)["slug"]
    r = tus_create(admin, slug, 101)
    assert r.status_code == 413 and r.json()["error"] == "quota_exceeded"


def test_default_quota_setting():
    env = {"SHARE_SECRET": "s" * 32, "SHARE_PUBLIC_URL": "https://share.example.com"}
    assert load_settings(env).default_quota == GiB
    assert load_settings({**env, "SHARE_DEFAULT_QUOTA_GB": " 50 "}).default_quota == 50 * GiB
    assert load_settings({**env, "SHARE_DEFAULT_QUOTA_GB": "Unlimited"}).default_quota is None
    for bad in ("0", "-1", "1.5", "много", "10G"):
        with pytest.raises(ValueError, match="SHARE_DEFAULT_QUOTA_GB"):
            load_settings({**env, "SHARE_DEFAULT_QUOTA_GB": bad})
