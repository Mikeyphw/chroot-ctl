#!/usr/bin/env bash
set -euo pipefail
for stage in restore-reset restore-go restore-tmux restore-seal; do scripts/devtool/root-module-stage.sh "$stage"; done
