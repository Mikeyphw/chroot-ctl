#!/usr/bin/env bash
set -euo pipefail

go run ./cmd/cli-contract-gen --check
go test ./internal/module ./internal/repoctl -run 'CHR15|ValidateModuleRuntimeReleaseTrust|TestRenderGoNativeModule|TestZipSkipsExistingDestinationInsideModuleTree' -count=1
go test ./internal/services ./internal/bridge ./internal/cli -run 'CHR15|module_build|ModuleBuild|ContractCommandSurface|EveryFrozenPathParses' -count=1
