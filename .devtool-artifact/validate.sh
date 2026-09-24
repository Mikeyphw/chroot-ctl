#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# WR12+ authoritative source validation. The standalone Android/Gradle product
# is retired; root-module lifecycle/package validation is owned by the
# chrootctl_root_module Devtool workflow rather than a deleted Gradle aggregate.
go run ./cmd/repoctl validate
