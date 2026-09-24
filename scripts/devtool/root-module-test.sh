#!/usr/bin/env bash
set -euo pipefail
for stage in test-webui test-go test-tmux test-seal; do scripts/devtool/root-module-stage.sh "$stage"; done
