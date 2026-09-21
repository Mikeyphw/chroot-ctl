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
  system/bin/chrootctl \
  webroot/index.html \
  webroot/index.js \
  webroot/chrootctl.js \
  webroot/kernelsu.js
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
