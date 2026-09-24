#!/usr/bin/env bash
set -euo pipefail
for stage in build-tmux build-tmux-verify build-repoctl build-runtime build-module build-seal; do scripts/devtool/root-module-stage.sh "$stage"; done
