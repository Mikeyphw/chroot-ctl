#!/usr/bin/env bash
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
CHECK="$ROOT/scripts/ci/require-hosted-ndk.sh"
T=$(mktemp -d "${TMPDIR:-/tmp}/chrootctl-ndk-check.XXXXXXXX")
trap 'rm -rf -- "$T"' EXIT
SDK="$T/sdk"
REV=29.0.14206865
NDK="$SDK/ndk/$REV"
PROPS="$NDK/source.properties"
BIN="$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android26-clang"
mkdir -p "$(dirname "$BIN")" "$T/ambient/ndk"
printf '%s\n' '#!/bin/sh' 'exit 0' > "$BIN"
chmod +x "$BIN"
printf 'Pkg.Desc = Android NDK\r\nPkg.Revision = %s\r\nPkg.BaseRevision = %s\r\n' "$REV" "$REV" > "$PROPS"
# Regression: the old preflight incorrectly selected ambient ANDROID_NDK_HOME.
export ANDROID_NDK_HOME="$T/ambient/ndk"
export ANDROID_NDK_ROOT="$T/ambient/ndk"
[[ $("$CHECK" "$SDK" "$REV" 26) == "$NDK" ]] || { echo FAIL_CC13_AMBIENT_NDK_OVERRIDDEN >&2; exit 1; }
reject(){
  if "$CHECK" "$SDK" "$REV" 26 >"$T/out" 2>"$T/err"; then
    echo 'FAIL_CC13_ACCEPTED_UNVERIFIED_NDK' >&2; exit 1
  fi
  [[ -s "$T/err" ]] || { echo FAIL_CC13_MISSING_ERROR >&2; exit 1; }
}
printf '%s\n' 'Pkg.Revision = 28.2.13676358' > "$PROPS"
reject
grep -q 'actual=28.2.13676358' "$T/err"
printf '%s\n' "Pkg.Revision = $REV" "Pkg.Revision = $REV" > "$PROPS"
reject
printf '%s\n' 'Pkg.Desc = Android NDK' > "$PROPS"
reject
printf 'Pkg.Revision = %s\r\n' "$REV" > "$PROPS"
chmod -x "$BIN"
reject
chmod +x "$BIN"
[[ $("$CHECK" "$SDK" "$REV" 26) == "$NDK" ]]
# Never downgrade from API 26 merely because a different compiler exists.
if "$CHECK" "$SDK" "$REV" 24 >"$T/out" 2>"$T/err"; then
  echo FAIL_CC13_ACCEPTED_API24 >&2; exit 1
fi
rm -f "$BIN"
reject
printf '%s\n' 'PASS_CC13_HOSTED_NDK_PATH_VERSION_AND_API26_NEGATIVES'
