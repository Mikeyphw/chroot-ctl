#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

go run ./cmd/cli-contract-gen --check
go test ./internal/operations ./internal/bridge ./internal/repoctl -run 'CHR18|AndroidOperationRoomRecovery|FindByRequestID|ResponseSchema|Operation|FrozenCapabilities' -count=1
go test ./... -run '^$' -count=1
