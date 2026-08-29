#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUT=${1:-"$ROOT/.devtool/build/go/android-arm64-sqlite/sqlite-compat"}
API=${CHROOTCTL_ANDROID_API:-26}
NDK_VERSION=${CHROOTCTL_ANDROID_NDK_VERSION:-29.0.14206865}
REQUIRE=${CHROOTCTL_GO02_REQUIRE_ANDROID:-0}

fail() {
  echo "GO02 Android SQLite build: $*" >&2
  exit 1
}

resolve_cc() {
  if [[ -n ${CHROOTCTL_ANDROID_CC:-} ]]; then
    [[ ${CHROOTCTL_ANDROID_CC} = /* ]] || fail "CHROOTCTL_ANDROID_CC must be an absolute path"
    [[ -x ${CHROOTCTL_ANDROID_CC} ]] || fail "compiler is not executable: ${CHROOTCTL_ANDROID_CC}"
    printf '%s\n' "$CHROOTCTL_ANDROID_CC"
    return 0
  fi

  if [[ -n ${PREFIX:-} && -x ${PREFIX}/bin/clang && ${PREFIX} == /data/data/com.termux/* ]]; then
    printf '%s\n' "${PREFIX}/bin/clang"
    return 0
  fi
  if [[ -x /data/data/com.termux/files/usr/bin/clang ]]; then
    printf '%s\n' /data/data/com.termux/files/usr/bin/clang
    return 0
  fi

  local root candidate
  for root in "${ANDROID_NDK_ROOT:-}" "${ANDROID_NDK_HOME:-}" \
      "${ANDROID_SDK_ROOT:-}/ndk/${NDK_VERSION}" "${ANDROID_HOME:-}/ndk/${NDK_VERSION}"; do
    [[ -n $root && $root != /ndk/* && -d $root ]] || continue
    candidate=$(find "$root/toolchains/llvm/prebuilt" -type f -name "aarch64-linux-android${API}-clang" -perm -u+x -print -quit 2>/dev/null || true)
    if [[ -n $candidate ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

if ! CC_PATH=$(resolve_cc); then
  if [[ $REQUIRE == 1 ]]; then
    fail "no Android arm64 C compiler found (set CHROOTCTL_ANDROID_CC or install NDK ${NDK_VERSION})"
  fi
  echo "GO02 Android SQLite build: skipped; no Android arm64 C compiler found" >&2
  exit 0
fi

mkdir -p "$(dirname -- "$OUT")"
echo "GO02 Android SQLite compiler: $CC_PATH" >&2
(
  cd "$ROOT"
  GOOS=android GOARCH=arm64 CGO_ENABLED=1 CC="$CC_PATH" \
    go build -trimpath -tags android -o "$OUT" ./cmd/sqlite-compat
)

[[ -s $OUT ]] || fail "Go produced no Android sqlite-compat executable"
if command -v file >/dev/null 2>&1; then
  DESC=$(file "$OUT")
  echo "$DESC" >&2
  case "$DESC" in
    *aarch64*|*ARM\ aarch64*|*ARM64*) ;;
    *) fail "unexpected Android executable architecture: $DESC" ;;
  esac
fi
printf '%s\n' "$OUT"
