# Share for macOS

A menu bar app: drop files on it (or click to choose), get a link, copy it. Uploads go over
tus to your share server; the link is the same `/s/<slug>` as in the web interface.

## Build

Needs Xcode (the SwiftUI macros are not in the Command Line Tools) and macOS 14+.

```sh
cd macos
./build.sh            # builds build/Share.app
./build.sh install    # also copies it to /Applications and launches it
```

The app is signed ad hoc, so it runs only on the Mac it was built on.

## Finder: "Copy link with Share"

`Sources/ShareExtension` is a share extension: it appears in the Finder share menu (and in
the share sheet of other apps) once the app has been launched from /Applications. It sends
the files to the app through `share-app://upload?path=…&expires=3600`; the app uploads them
to a one-hour link, copies the link and shows it in the popover. If the item is missing,
enable it in System Settings → General → Login Items & Extensions → Sharing.

## Icons

`Icons/MenuBarIcon.svg` is the status item (loaded as a template image), `Icons/AppIcon.png`
becomes `AppIcon.icns` at build time (Dock, Finder, the share menu). Both were drawn by
ChatGPT; `Icons/prompts.json` keeps the prompts and the conversation link for redoing them.

## Sign-in

"Sign in" opens `<server>/connect` in the browser with a PKCE challenge. After signing in
there, you confirm the connection, the server issues a one-time code and the browser hands it
back through the `share-app://` URL scheme. The app exchanges the code and its verifier for a
session token (`POST /api/auth/app/token`) and keeps the token in the login keychain; every API
call sends it as `Authorization: Bearer`. "Sign out" ends that session on the server.

The server is `https://share.nikitakiselev.com` by default. Another one:

```sh
defaults write ru.nikitakiselev.share-app serverURL http://127.0.0.1:8000
```

## Tests

```sh
swift test                                   # PKCE only
SHARE_TEST_SERVER=http://127.0.0.1:8000 SHARE_TEST_TOKEN=<session token> swift test
```

The second form uploads a 10 MiB file to a running backend through the real tus client and
checks the result. A token comes from `/api/auth/app/token`, or from a browser session cookie
(`share_session`) — both are sessions.
