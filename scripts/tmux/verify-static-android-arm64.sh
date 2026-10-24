#!/usr/bin/env bash
set -euo pipefail

bin=${1:?usage: verify-static-android-arm64.sh TMUX [MANIFEST]}
manifest=${2:-$(dirname "$bin")/tmux-runtime-manifest.json}
checksum=$(dirname "$bin")/tmux.sha256

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "tmux verifier requires $1" >&2
    exit 127
  }
}
need sha256sum
need awk
need grep

READELF=${CHROOTCTL_TMUX_READELF:-$(command -v llvm-readelf || command -v readelf || true)}
[[ -n "$READELF" && -x "$READELF" ]] || {
  echo "tmux verifier requires llvm-readelf or readelf" >&2
  exit 127
}

[[ -f "$bin" && -x "$bin" && ! -L "$bin" ]] || {
  echo "tmux must be a regular executable" >&2
  exit 1
}
[[ -f "$manifest" && ! -L "$manifest" ]] || {
  echo "tmux runtime manifest missing/unsafe" >&2
  exit 1
}
[[ -f "$checksum" && ! -L "$checksum" ]] || {
  echo "tmux checksum file missing/unsafe" >&2
  exit 1
}

header=$("$READELF" -h "$bin")
printf '%s\n' "$header" | grep -Eq 'Class:[[:space:]]+ELF64' || {
  echo "tmux is not ELF64" >&2
  exit 1
}
printf '%s\n' "$header" | grep -Eq 'Machine:[[:space:]]+(AArch64|ARM aarch64)' || {
  echo "tmux is not AArch64" >&2
  exit 1
}

! "$READELF" -l "$bin" | grep -q 'INTERP' || {
  echo "tmux has a dynamic interpreter" >&2
  exit 1
}
! "$READELF" -d "$bin" 2>/dev/null | grep -q '(NEEDED)' || {
  echo "tmux has dynamic dependencies" >&2
  exit 1
}

sha=$(sha256sum "$bin" | awk '{print $1}')
expected=$(awk 'NR==1 {print $1}' "$checksum")
[[ $expected == "$sha" ]] || {
  echo "tmux checksum file mismatch" >&2
  exit 1
}

# Runtime provenance is authoritative in the canonical JSON manifest.  Keep
# these exact checks deliberately simple so verification has no jq/Python
# dependency and works both in native Termux validation and package sealing.
grep -Fq '"schemaVersion": 1' "$manifest"
grep -Fq '"component": "tmux"' "$manifest"
grep -Fq '"version": "3.7c"' "$manifest"
grep -Fq '"platform": "android"' "$manifest"
grep -Fq '"abi": "arm64-v8a"' "$manifest"
grep -Fq '"androidApi": 26' "$manifest"
grep -Fq '"libc": "bionic-static"' "$manifest"
grep -Fq '"ndkRevision": "29.0.14206865"' "$manifest"
grep -Fq '"linkage": "static"' "$manifest"
grep -Fq '"compression": "none"' "$manifest"
grep -Fq "\"sha256\": \"$sha\"" "$manifest"

# Source provenance must remain pinned as part of the runtime seal.
grep -Fq '"name":"tmux","version":"3.7c"' "$manifest"
grep -Fq '"name":"libevent","version":"2.1.12-stable"' "$manifest"
grep -Fq '"name":"ncurses","version":"6.5"' "$manifest"

# Deliberately do NOT execute "$bin" here.  The target is an Android runtime
# artifact; verification is structural + provenance based and uses no /tmp.
echo "verified static Android/arm64 tmux 3.7c: $sha"
