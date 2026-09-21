#!/usr/bin/env bash
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
A="$ROOT/out/tmux-repro-a/arm64-v8a"; B="$ROOT/out/tmux-repro-b/arm64-v8a"
CHROOTCTL_TMUX_OUTPUT="$A" CHROOTCTL_TMUX_WORK="$ROOT/out/tmux-repro-work-a" "$ROOT/scripts/tmux/build-static-android-arm64.sh"
CHROOTCTL_TMUX_OUTPUT="$B" CHROOTCTL_TMUX_WORK="$ROOT/out/tmux-repro-work-b" "$ROOT/scripts/tmux/build-static-android-arm64.sh"
a=$(sha256sum "$A/tmux"|awk '{print $1}'); b=$(sha256sum "$B/tmux"|awk '{print $1}')
[[ $a == "$b" ]] || { echo "tmux reproducibility failure: $a != $b" >&2; exit 1; }
echo "tmux reproducibility verified: $a"
