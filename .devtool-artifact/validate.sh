#!/usr/bin/env bash
set -euo pipefail

go run ./cmd/cli-contract-gen --check
go test ./internal/bridge ./internal/repoctl -run 'CHR17|BridgeProtocolV2|ResponseSchema|Timeline|ValidateBridgeProtocolV2Convergence' -count=1
