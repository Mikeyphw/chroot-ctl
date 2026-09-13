#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

go run ./cmd/cli-contract-gen --check
go test ./internal/logging ./internal/redaction ./internal/operations ./internal/services ./internal/repoctl ./internal/model -run 'CHR16|CHR10|ValidateTransferArtifactPlane|ValidateLoggingDiagnosticsAuditEvidence|TestLoggingContractAndFiltering|TestPythonModelFieldNamesAreMirrored' -count=1
go test ./... -run '^$' -count=1
