#!/usr/bin/env bash
set -euo pipefail
for stage in lint-go lint-native lint-seal; do scripts/devtool/root-module-stage.sh "$stage"; done
