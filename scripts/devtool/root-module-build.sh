#!/usr/bin/env sh
set -eu
echo "== chrootctl root module: build =="
mkdir -p out
go run ./cmd/repoctl build-module --output-dir out/module --zip out/chrootctl-magisk.zip --jobs "${DEVTOOL_MAX_WORKERS:-2}" --checksum
test -s out/chrootctl-magisk.zip
test -s out/chrootctl-magisk.zip.sha256
