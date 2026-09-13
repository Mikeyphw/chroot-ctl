#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

go run ./cmd/cli-contract-gen --check
go test ./internal/services ./internal/bridge ./internal/repoctl -run 'CHR19|AndroidProductWorkspace|StorageStatus|Logs' -count=1
go test ./... -run '^$' -count=1
