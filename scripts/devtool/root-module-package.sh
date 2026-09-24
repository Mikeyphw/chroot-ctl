#!/usr/bin/env bash
set -euo pipefail
for stage in package-preflight package-runtime package-webui package-evidence; do scripts/devtool/root-module-stage.sh "$stage"; done
