#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

go run ./cmd/cli-contract-gen --check
go test ./internal/repoctl -run 'CHR20|ValidateNavigationAdaptiveFinalReleaseSeal' -count=1
go run ./cmd/repoctl validate
if [ -x android/gradlew ]; then
  (cd android && ./gradlew --no-daemon --continue :chrootctlDebugValidation)
fi
