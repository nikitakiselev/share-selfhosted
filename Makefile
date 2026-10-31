# Release from the workstation: tests, macOS app, the author's LXC instance, a tag and a GitHub
# release. GitHub stores the code and the release; nothing is built there except the public
# Docker image that release.yml publishes on the tag for other people's installations.
#
#   make deploy                 # version from backend/pyproject.toml
#   make deploy VERSION=0.3.0   # bump the version first (pyproject + a "Release v0.3.0" commit)
#   make check | app | install-app | server | release

HOMELAB ?= $(HOME)/code/homelab
PVE_NODE ?= root@192.168.88.40
PYPROJECT = backend/pyproject.toml
CURRENT := $(shell sed -n 's/^version = "\(.*\)"/\1/p' $(PYPROJECT))
VERSION ?= $(CURRENT)
TAG = v$(VERSION)
ZIP = macos/build/Share-$(VERSION).zip

.PHONY: deploy check app install-app server release bump

deploy: check bump app server release install-app
	@echo "==> v$(VERSION) is out"

check:
	@echo "==> Tests"
	cd backend && .venv/bin/python -m pytest -q && uvx ruff check src tests
	cd frontend && npx vitest run --silent && npm run build

# Sets the version in pyproject and commits it; a no-op when VERSION is already there.
bump:
	@test -z "$$(git status --porcelain)" || { echo "commit or stash your changes first"; exit 1; }
	@test "$$(git branch --show-current)" = main || { echo "release from main only"; exit 1; }
	@! git rev-parse -q --verify refs/tags/$(TAG) >/dev/null || { echo "tag $(TAG) already exists"; exit 1; }
	@if [ "$(VERSION)" != "$(CURRENT)" ]; then \
	  sed -i '' 's/^version = ".*"/version = "$(VERSION)"/' $(PYPROJECT) && \
	  git commit -q -m "Release $(TAG)" $(PYPROJECT) && echo "==> Version $(VERSION) committed"; fi

app:
	@echo "==> macOS app $(VERSION)"
	VERSION=$(VERSION) macos/build.sh

install-app: app
	pkill -x Share 2>/dev/null || true
	rm -rf /Applications/Share.app && cp -R macos/build/Share.app /Applications/Share.app
	open /Applications/Share.app

# A ZFS snapshot on the node before every deploy, then the homelab script (frontend build,
# code and static files into the container, venv, env, service restart, checks).
server:
	@test -x $(HOMELAB)/infra/deploy/install_share.sh || { echo "no $(HOMELAB)/infra/deploy/install_share.sh (HOMELAB=...)"; exit 1; }
	@echo "==> ZFS snapshot data/share@$(TAG)"
	ssh -o ConnectTimeout=10 $(PVE_NODE) 'zfs snapshot data/share@$(TAG)-$$(date +%Y%m%d-%H%M)'
	cd $(HOMELAB) && SHARE_APP_SRC=$(CURDIR) ./infra/deploy/install_share.sh deploy

release:
	@test -f $(ZIP) || { echo "no $(ZIP): run make app"; exit 1; }
	git push -q origin main
	git tag -a $(TAG) -m "Release $(TAG)"
	git push -q origin $(TAG)
	gh release create $(TAG) --title "$(TAG)" --generate-notes $(ZIP)
