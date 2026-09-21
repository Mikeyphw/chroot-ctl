#!/usr/bin/env sh
set -eu
echo "== chrootctl root module: build =="
mkdir -p out
TMUX_OUT="${CHROOTCTL_TMUX_OUTPUT:-$PWD/out/tmux/arm64-v8a}"
if [ "${CHROOTCTL_SKIP_TMUX_BUILD:-0}" != "1" ]; then
  scripts/tmux/build-static-android-arm64.sh
fi
scripts/tmux/verify-static-android-arm64.sh "$TMUX_OUT/tmux" "$TMUX_OUT/tmux-runtime-manifest.json"
export CHROOTCTL_TMUX_PATH="$TMUX_OUT/tmux"
export CHROOTCTL_REQUIRE_TMUX=1
go run ./cmd/repoctl build-module --output-dir out/module --zip out/chrootctl-magisk.zip --jobs "${DEVTOOL_MAX_WORKERS:-2}" --checksum
test -s out/chrootctl-magisk.zip
test -s out/chrootctl-magisk.zip.sha256
