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
echo "repoctl: compiling build tool (cold Go/CGO caches may take several minutes)..."
go build -v -o out/repoctl-devtool ./cmd/repoctl
echo "repoctl: build tool ready; rendering Android runtime/module..."
out/repoctl-devtool build-module --output-dir out/module --zip out/chrootctl.zip --jobs "${DEVTOOL_MAX_WORKERS:-2}" --checksum
test -s out/chrootctl.zip
test -s out/chrootctl.zip.sha256
scripts/devtool/root-module-evidence.sh record root_build 'scripts/devtool/root-module-build.sh'
