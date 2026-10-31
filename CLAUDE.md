# share-selfhosted

Self-hosted file sharing by links: resumable tus uploads, video player, ZIP, passwords and expiry.

- `backend/` — Starlette + SQLite + ffmpeg, package `src/share_app`, tests in `tests/`.
- `frontend/` — Vue 3 + Vite + TypeScript + Tailwind v4; the build is served by the backend as static files.
- `macos/` — SwiftPM menu bar app (SwiftUI, macOS 14+); `./build.sh` makes `build/Share.app`, needs Xcode.

## Commands

```bash
# backend (media tests need ffmpeg/ffprobe in PATH)
cd backend && uv venv -p 3.12 && uv pip install -e '.[dev]'
.venv/bin/python -m pytest -q
uvx ruff check src tests

# frontend
cd frontend && npm ci
npm run build && npx vitest run

# local run: see backend/README.md

# image
docker build -t share-selfhosted .

# macOS app (see macos/README.md)
cd macos && ./build.sh && swift test
```

## Non-obvious

- A file on disk lives under its UUID7 (`<data>/{uploads,files,derived}/<id>`); the name is only in
  the DB, a user-supplied name never ends up in a path. Do not change `storage.FILE_ID_RE` without a
  migration: on start `cleanup.remove_orphans` deletes everything that does not match it.
- Recipients see only fully uploaded files (`db.ready_files`): the share page, the OG preview, the ZIP.
- The link is created on the first drop (tus needs somewhere to upload to), but "New link" shows it
  only once everything is uploaded. After a reload the page brings the link back only if it still
  has unfinished uploads.
- In the upload engine `name` is the source file name (it identifies the file when resuming),
  `displayName` is the name in the link. Do not mix them up.
- Sign-in is by email only; `login` (username) is for display. Invites are issued for an email.
  Tokens are stored only as a hash, so a link cannot be shown again: "New link" (`/renew`) issues a
  fresh one and kills the old one.
- The desktop app signs in through `/connect?challenge=` (PKCE): the browser session calls
  `POST /api/auth/app/connect` for a one-time code, the page hands it to `share-app://connect?code=`,
  the app exchanges it at `POST /api/auth/app/token` for an ordinary session. Codes live in process
  memory (`Context.app_codes`). A session sent as `Authorization: Bearer` skips the Origin check:
  it has no cookie, so a web page cannot forge it.
- Every user has a permanent quota `users.quota_bytes` (NULL — unlimited). New users get the quota
  of their invite, `SHARE_DEFAULT_QUOTA_GB` by default. Used = sum of `files.size`, unfinished
  uploads included. The quota is checked only when a tus upload is created: a started upload always
  completes. A quota below the used space deletes nothing, it only blocks new uploads.
- `/api/admin/*` requires the admin role **and** an IP from `SHARE_INTERNAL_NETS` (loopback is
  always allowed). `/api/app/*` and tus work only with a session and only on the user's own data:
  someone else's slug/file_id answers 404. State-changing `/api/*` requests with a session cookie
  and without a matching `Origin` (`SHARE_PUBLIC_URL` or the request `Host`) get 403.
- i18n: the UI uses the browser language (`ru*` → Russian, otherwise English), no switcher.
  Dictionaries `frontend/src/locales/en.ts` and `ru.ts` have the same keys. API errors are shown by
  the `error` code plus numeric fields; the server's `message` is English, for debugging (shown only
  for codes the UI does not know). Server-rendered pages and OG use `SHARE_LANGUAGE`.
- DB schema: only a fresh install or the current version is supported, anything else fails on
  start. There are no migrations from older schemas.

## Deploying the author's instance

`make deploy [VERSION=x.y.z]` from the workstation: tests, macOS app into `macos/build`, ZFS
snapshot + the homelab script (`~/code/homelab/infra/deploy/install_share.sh deploy`, see
`~/code/homelab/infra/share/CLAUDE.md`), then the tag, `git push` and a GitHub release with the
app zip. share.nikitakiselev.com is not run from the published image: tagging `vX.Y.Z` only
publishes the public image through release.yml.
