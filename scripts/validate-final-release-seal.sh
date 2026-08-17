#!/usr/bin/env bash
set -euo pipefail
ROOT="${DEVTOOL_REPO_ROOT:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"
exec python3 "$ROOT/scripts/final-release-seal.py" "$@"
