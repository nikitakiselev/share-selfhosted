# share-app — the share backend

```bash
uv venv -p 3.12 && uv pip install -e '.[dev]'
uv run pytest                      # media tests need ffmpeg/ffprobe in PATH

# local run (http, so cookies are not Secure); sign in as admin@example.com / local-password
export SHARE_DATA_DIR=/tmp/share-data SHARE_STATIC_DIR=../frontend/dist \
       SHARE_SECRET=$(openssl rand -hex 32) \
       SHARE_PUBLIC_URL=http://127.0.0.1:8000 SHARE_HOST=127.0.0.1 \
       SHARE_ADMIN_EMAIL=admin@example.com SHARE_ADMIN_PASSWORD=local-password
.venv/bin/share-app
```

Users sign in **by email**; the username (`login`) is only for display. The first admin is
created on start while there are no users: email from `SHARE_ADMIN_EMAIL`, password from
`SHARE_ADMIN_PASSWORD` (at least 10 characters), username from the part of the email before `@`.
After that the password lives in the database and the variables are ignored (a warning in the
log suggests removing `SHARE_ADMIN_PASSWORD`). With no users and no variables the server does
not start. Everyone else joins by an invite from "Users": the invite is issued for an email,
and the person picks a username and password via the link.

Every user has a permanent storage quota (`users.quota_bytes`, NULL — unlimited). A new user
gets the quota from the invite, by default `SHARE_DEFAULT_QUOTA_GB` (a whole number of GiB, 1 or
more, or `unlimited`; 1 without the variable). An admin changes anyone's quota, their own
included, on "Users". The first admin is created without a quota.

```bash
# change a password (stdin, one line, at least 10 characters); all of the user's sessions are revoked
printf %s 'new-password' | .venv/bin/share-app set-password --email admin@example.com
# change an email (one taken by another user is refused)
.venv/bin/share-app set-email --email admin@example.com --new-email owner@example.com
```

The Vite proxy to the backend uses `changeOrigin: false` (the default): the backend checks the
`Origin` of state-changing requests against `Host` and answers 403 to a session cookie without
`Origin`.
