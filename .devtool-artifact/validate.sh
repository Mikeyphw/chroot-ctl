#!/usr/bin/env bash
set -euo pipefail

go run ./cmd/cli-contract-gen --check
go test ./internal/clipboard ./internal/cli ./internal/repoctl -run 'CHR14|ValidateClipboardPrivilegedIntegration|PathsToken|Wrapper|ContractCommandSurface|EveryFrozenPathParses' -count=1
