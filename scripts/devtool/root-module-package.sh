#!/usr/bin/env sh
set -eu

echo "== chrootctl root module: package/seal =="

ZIP="out/chrootctl-magisk.zip"
SUM="${ZIP}.sha256"
TREE="out/module"

test -s "$ZIP" || { echo "missing module ZIP: $ZIP" >&2; exit 1; }
test -s "$SUM" || { echo "missing module checksum: $SUM" >&2; exit 1; }
test -d "$TREE" || { echo "missing expanded module tree: $TREE" >&2; exit 1; }

expected="$(awk 'NR==1 {print $1}' "$SUM")"
actual="$(sha256sum "$ZIP" | awk '{print $1}')"
[ -n "$expected" ] && [ "$expected" = "$actual" ] || {
  echo "module checksum mismatch" >&2
  exit 1
}

for required in \
  module.prop \
  post-fs-data.sh \
  service.sh \
  action.sh \
  system/bin/chrootctl \
  webroot/index.html \
  webroot/index.js \
  webroot/chrootctl.js \
  webroot/kernelsu.js \
  runtime/arm64-v8a/chrootctl \
  runtime/arm64-v8a/runtime-manifest.json \
  runtime/arm64-v8a/tmux \
  runtime/arm64-v8a/tmux-runtime-manifest.json \
  runtime/arm64-v8a/tmux.sha256
do
  [ -e "$TREE/$required" ] || {
    echo "module package missing required path: $required" >&2
    exit 1
  }
done

# Seal the architecture that replaced the retired standalone Android app.
grep -Fq '[targets.chrootctl_root_module]' .devtool.toml || {
  echo "chrootctl_root_module Devtool target missing" >&2
  exit 1
}
if grep -Fq '[targets.chrootctl_android]' .devtool.toml; then
  echo "retired standalone Android target unexpectedly returned" >&2
  exit 1
fi
# Ensure the packaged backend is an actual executable artifact.
[ -x "$TREE/system/bin/chrootctl" ] || {
  echo "packaged chrootctl backend is not executable" >&2
  exit 1
}

echo "Root-module package seal passed."

./scripts/tmux/verify-static-android-arm64.sh "$TREE/runtime/arm64-v8a/tmux" "$TREE/runtime/arm64-v8a/tmux-runtime-manifest.json"

# Verify checksum sidecar and the exact bytes stored in the module ZIP.
tmux_tree_sha="$(sha256sum "$TREE/runtime/arm64-v8a/tmux" | awk '{print $1}')"
tmux_sidecar_sha="$(awk 'NR==1 {print $1}' "$TREE/runtime/arm64-v8a/tmux.sha256")"
[ "$tmux_tree_sha" = "$tmux_sidecar_sha" ] || { echo "packaged tmux checksum sidecar mismatch" >&2; exit 1; }
command -v unzip >/dev/null 2>&1 || { echo "unzip is required for package seal" >&2; exit 127; }
tmux_zip_sha="$(unzip -p "$ZIP" runtime/arm64-v8a/tmux | sha256sum | awk '{print $1}')"
[ "$tmux_zip_sha" = "$tmux_tree_sha" ] || { echo "module ZIP tmux bytes differ from sealed runtime" >&2; exit 1; }

# CUX post-roadmap hotfix: rclone is optional, but when the runtime manifest
# inventories it the package seal must prove the expanded tree and ZIP contain
# the same executable bytes. This closes the gap where UI/runtime discovery
# could claim a packaged optional executable without package-level byte proof.
RUNTIME_MANIFEST="$TREE/runtime/arm64-v8a/runtime-manifest.json"
if grep -Eq '"[Pp]ath"[[:space:]]*:[[:space:]]*"rclone"' "$RUNTIME_MANIFEST"; then
  RCLONE="$TREE/runtime/arm64-v8a/rclone"
  [ -f "$RCLONE" ] && [ -x "$RCLONE" ] && [ ! -L "$RCLONE" ] || {
    echo "runtime manifest inventories rclone but packaged executable is missing/unsafe" >&2
    exit 1
  }
  rclone_tree_sha="$(sha256sum "$RCLONE" | awk '{print $1}')"
  rclone_zip_sha="$(unzip -p "$ZIP" runtime/arm64-v8a/rclone | sha256sum | awk '{print $1}')"
  [ "$rclone_tree_sha" = "$rclone_zip_sha" ] || {
    echo "module ZIP rclone bytes differ from sealed runtime" >&2
    exit 1
  }
fi


# SWUI-04 standalone WebUI release seal.
grep -Fq '127.0.0.1:0' internal/standalonewebui/server.go || { echo "standalone WebUI is not loopback-only" >&2; exit 1; }
# Inspect actual literal HTTP route registrations, not comments/tests/denylist strings.
# Generic privileged endpoints must never be registered by the standalone server.
if grep -REn 'mux\.Handle(Func)?\("/api/v1/(shell|exec|argv|root-rpc|rpc|command)(/|"|\?)' \
    internal/standalonewebui/*.go >/dev/null 2>&1; then
  echo "unsafe generic privileged HTTP route registered" >&2
  exit 1
fi
grep -Fq 'action.sh' internal/module/module.go || { echo "standalone Action launcher missing" >&2; exit 1; }
grep -Fq 'case <-srv.Done()' cmd/chrootctl/main.go || { echo "standalone server process does not exit after idle shutdown" >&2; exit 1; }
