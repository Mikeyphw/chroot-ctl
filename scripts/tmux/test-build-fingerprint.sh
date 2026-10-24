#!/usr/bin/env bash
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
# Evaluate the function exactly as defined in the production builder while
# skipping its network and Android toolchain initialization.
function_source=$(sed -n '/^build_fingerprint() {/,/^}/p' "$ROOT/scripts/tmux/build-static-android-arm64.sh")
[[ "$function_source" == build_fingerprint* ]] || { echo 'tmux fingerprint function missing' >&2; exit 1; }
eval "$function_source"
TMUX_VERSION=3.7c TMUX_SHA256=fixture-tmux
LIBEVENT_VERSION=2.1.12-stable LIBEVENT_SHA256=fixture-event
NCURSES_VERSION=6.5 NCURSES_SHA256=fixture-curses
ANDROID_API=26 NDK_REVISION=29.0.14206865
CC=fixture-cc AR=fixture-ar RANLIB=fixture-ranlib STRIP=fixture-strip
SOURCE_DATE_EPOCH=0 CHROOTCTL_TMUX_HOSTED_NDK=1
first=$(build_fingerprint)
[[ "$first" =~ ^[a-f0-9]{64}$ ]] || { echo 'invalid fingerprint' >&2; exit 1; }
second=$(build_fingerprint)
[[ "$first" == "$second" ]] || { echo 'fingerprint is not deterministic' >&2; exit 1; }
CHROOTCTL_TMUX_HOSTED_NDK=0
third=$(build_fingerprint)
[[ "$third" =~ ^[a-f0-9]{64}$ && "$first" != "$third" ]] || { echo 'host lane absent from fingerprint' >&2; exit 1; }
CHROOTCTL_TMUX_HOSTED_NDK=1 ANDROID_API=27
fourth=$(build_fingerprint)
[[ "$first" != "$fourth" ]] || { echo 'Android API absent from fingerprint' >&2; exit 1; }
printf '%s\n' PASS_CC11_TMUX_HOSTED_BUILD_FINGERPRINT
