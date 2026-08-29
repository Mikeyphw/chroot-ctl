#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TMP=$(mktemp -d "${TMPDIR:-/tmp}/chrootctl-go02.XXXXXX")
trap 'rm -rf "$TMP"' EXIT INT TERM
DB="$TMP/python-created.sqlite3"

cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

echo 'GO02: Python creates the canonical registry database'
python3 scripts/go02-sqlite-fixture.py create "$DB" > "$TMP/python-create.json"

echo 'GO02: Go tests and vet'
CGO_ENABLED=1 go test ./...
CGO_ENABLED=1 go vet ./...

echo 'GO02: Go opens and mutates the Python-created database'
CGO_ENABLED=1 go run ./cmd/sqlite-compat --db "$DB" --mutate > "$TMP/go-mutate.json"

echo 'GO02: Python reopens and verifies the Go-mutated database'
python3 scripts/go02-sqlite-fixture.py verify "$DB" > "$TMP/python-verify.json"

echo 'GO02: keep the original Go backend Android/arm64 CGO-free build healthy'
mkdir -p "$TMP/main"
CGO_ENABLED=0 GOOS=android GOARCH=arm64 go build -trimpath -o "$TMP/main/chrootctl" ./cmd/chrootctl

echo 'GO02: compile the SQLite compatibility helper for Android/arm64 when a compiler is available'
bash scripts/build-go02-android-sqlite.sh "$TMP/sqlite-compat-android-arm64"

echo 'GO02 SQLite compatibility gate passed.'
cat "$TMP/python-verify.json"
