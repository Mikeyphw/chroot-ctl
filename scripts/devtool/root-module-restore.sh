#!/usr/bin/env sh
set -eu
echo "== chrootctl root module: restore =="
command -v go >/dev/null 2>&1 || { echo "go is required" >&2; exit 127; }
command -v node >/dev/null 2>&1 || { echo "node is required for WebUI validation" >&2; exit 127; }
go mod download
go mod verify

# Restore and cryptographically verify pinned TMUX-01 source archives.
CHROOTCTL_TMUX_FETCH_ONLY=1 scripts/tmux/build-static-android-arm64.sh
