#!/usr/bin/env bash
set -euo pipefail

TMUX_VERSION=3.7c
TMUX_SHA256=7c60cae9a0e25288e2e24750aafc9e8800fc7fd4555e447e1b29ee4201cfb3bf
LIBEVENT_VERSION=2.1.12-stable
LIBEVENT_SHA256=92e6de1be9ec176428fd2367677e61ceffc2ee1cb119035037a27d346b0403bb
NCURSES_VERSION=6.5
NCURSES_SHA256=136d91bc269a9a5785e5f9e980bc76ab57428f604ce3e5a5a90cebc767971cc6
ANDROID_API=${CHROOTCTL_TMUX_ANDROID_API:-24}
NDK_REVISION=${CHROOTCTL_TMUX_NDK_REVISION:-29.0.14206865}
JOBS=${DEVTOOL_MAX_WORKERS:-${CHROOTCTL_TMUX_JOBS:-2}}
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
CACHE=${CHROOTCTL_TMUX_CACHE:-$ROOT/.devtool/cache/tmux-sources}
WORK=${CHROOTCTL_TMUX_WORK:-$ROOT/out/tmux-build}
OUT=${CHROOTCTL_TMUX_OUTPUT:-$ROOT/out/tmux/arm64-v8a}
PREFIX=$WORK/prefix
SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-0}
export SOURCE_DATE_EPOCH TZ=UTC LC_ALL=C

need(){ command -v "$1" >/dev/null 2>&1 || { echo "tmux build requires $1" >&2; exit 127; }; }
for x in curl sha256sum; do need "$x"; done

fetch(){ local url=$1 dst=$2 sum=$3; mkdir -p "$CACHE"; if [[ ! -f $dst ]]; then curl -fL --retry 3 --proto '=https' "$url" -o "$dst.tmp"; mv "$dst.tmp" "$dst"; fi; echo "$sum  $dst" | sha256sum -c - >/dev/null; }
TMUX_TAR=$CACHE/tmux-$TMUX_VERSION.tar.gz
EVENT_TAR=$CACHE/libevent-$LIBEVENT_VERSION.tar.gz
CURSES_TAR=$CACHE/ncurses-$NCURSES_VERSION.tar.gz
fetch "https://github.com/tmux/tmux/releases/download/$TMUX_VERSION/tmux-$TMUX_VERSION.tar.gz" "$TMUX_TAR" "$TMUX_SHA256"
fetch "https://github.com/libevent/libevent/releases/download/release-$LIBEVENT_VERSION/libevent-$LIBEVENT_VERSION.tar.gz" "$EVENT_TAR" "$LIBEVENT_SHA256"
fetch "https://ftp.gnu.org/gnu/ncurses/ncurses-$NCURSES_VERSION.tar.gz" "$CURSES_TAR" "$NCURSES_SHA256"
[[ ${CHROOTCTL_TMUX_FETCH_ONLY:-0} == 1 ]] && { echo "tmux sources restored and verified"; exit 0; }
for x in tar make awk sed grep; do need "$x"; done

find_cc(){
  if [[ -n ${CHROOTCTL_TMUX_CC:-} ]]; then printf '%s\n' "$CHROOTCTL_TMUX_CC"; return; fi
  local ndk=${ANDROID_NDK_HOME:-${ANDROID_NDK_ROOT:-}}
  local -a candidates=()
  [[ -n $ndk ]] && candidates+=("$ndk")
  [[ -n ${ANDROID_NDK_HOME:-} ]] && candidates+=("$ANDROID_NDK_HOME")
  [[ -n ${ANDROID_NDK_ROOT:-} ]] && candidates+=("$ANDROID_NDK_ROOT")
  [[ -n ${ANDROID_HOME:-} ]] && candidates+=("$ANDROID_HOME/ndk/$NDK_REVISION")
  [[ -n ${ANDROID_SDK_ROOT:-} ]] && candidates+=("$ANDROID_SDK_ROOT/ndk/$NDK_REVISION")
  [[ -n ${PREFIX:-} ]] && candidates+=("$PREFIX/share/android-sdk/ndk/$NDK_REVISION" "$PREFIX/opt/android-sdk/ndk/$NDK_REVISION")
  candidates+=(
    "$HOME/Android/Sdk/ndk/$NDK_REVISION"
    "$HOME/android-sdk/ndk/$NDK_REVISION"
    "/opt/android-sdk/ndk/$NDK_REVISION"
  )
  local root p
  for root in "${candidates[@]}"; do
    [[ -d $root ]] || continue
    for p in "$root"/toolchains/llvm/prebuilt/*/bin/aarch64-linux-android"$ANDROID_API"-clang; do
      [[ -x $p ]] && { printf '%s\n' "$p"; return; }
    done
  done
  echo "Android NDK $NDK_REVISION arm64 clang for API $ANDROID_API not found; set ANDROID_NDK_HOME/ANDROID_NDK_ROOT or CHROOTCTL_TMUX_CC" >&2
  exit 127
}
NDK_CC=$(find_cc)
NDK_ROOT=$(CDPATH= cd -- "$(dirname -- "$NDK_CC")/../../../../../" && pwd)
[[ -f "$NDK_ROOT/source.properties" ]] || { echo "NDK source.properties missing: $NDK_ROOT" >&2; exit 1; }
actual_ndk=$(sed -n 's/^Pkg.Revision[[:space:]]*=[[:space:]]*//p' "$NDK_ROOT/source.properties" | head -1)
[[ $actual_ndk == "$NDK_REVISION" ]] || { echo "tmux build requires Android NDK $NDK_REVISION, found ${actual_ndk:-unknown}" >&2; exit 1; }

TOOLCHAIN=$(CDPATH= cd -- "$(dirname -- "$NDK_CC")/.." && pwd)
if [[ -n ${CHROOTCTL_TMUX_CC:-} ]]; then
  CC="$CHROOTCTL_TMUX_CC"
else
  HOST_CLANG=${CHROOTCTL_TMUX_HOST_CLANG:-$(command -v clang || true)}
  [[ -n $HOST_CLANG && -x $HOST_CLANG ]] || { echo "native Termux clang is required" >&2; exit 127; }
  RESOURCE_DIR=$("$HOST_CLANG" -print-resource-dir)
  BUILTINS="$RESOURCE_DIR/lib/linux/libclang_rt.builtins-aarch64-android.a"
  # PREFIX is the tmux staging prefix in this script, not Termux's prefix.
  # Derive the native Termux prefix from the actual clang executable unless
  # explicitly overridden.
  HOST_CLANG_REAL=$(readlink -f "$HOST_CLANG" 2>/dev/null || printf '%s\n' "$HOST_CLANG")
  TERMUX_PREFIX=${CHROOTCTL_TMUX_TERMUX_PREFIX:-$(CDPATH= cd -- "$(dirname -- "$HOST_CLANG_REAL")/.." && pwd)}
  TERMUX_LIB=${CHROOTCTL_TMUX_TERMUX_LIB:-$TERMUX_PREFIX/lib}
  UNWIND="$TERMUX_LIB/libunwind.a"
  [[ -f $BUILTINS ]] || { echo "Termux clang Android builtins missing: $BUILTINS" >&2; exit 1; }
  [[ -f $UNWIND ]] || { echo "Termux static libunwind missing: $UNWIND" >&2; exit 1; }
  CC="$HOST_CLANG --target=aarch64-linux-android$ANDROID_API --sysroot=$TOOLCHAIN/sysroot -resource-dir=$RESOURCE_DIR"
fi
AR=${CHROOTCTL_TMUX_AR:-$(command -v llvm-ar || true)}
RANLIB=${CHROOTCTL_TMUX_RANLIB:-$(command -v llvm-ranlib || true)}
STRIP=${CHROOTCTL_TMUX_STRIP:-$(command -v llvm-strip || true)}
for x in "$AR" "$RANLIB" "$STRIP"; do [[ -n $x && -x $x ]] || { echo "missing native Termux LLVM tool: ${x:-unset}" >&2; exit 127; }; done

BUILD_FINGERPRINT_FILE="$WORK/.chrootctl-tmux-build-fingerprint"
build_fingerprint() {
  {
    printf '%s\n' \
      "schema=2" \
      "tmux=$TMUX_VERSION:$TMUX_SHA256" \
      "libevent=$LIBEVENT_VERSION:$LIBEVENT_SHA256" \
      "ncurses=$NCURSES_VERSION:$NCURSES_SHA256" \
      "android_api=$ANDROID_API" \
      "ndk=$NDK_REVISION" \
      "cc=$CC" \
      "ar=$AR" \
      "ranlib=$RANLIB" \
      "strip=$STRIP" \
      "cflags=-Os -fPIC -ffile-prefix-map=WORK=. -fdebug-prefix-map=WORK=." \
      "ldflags=static,--build-id=none" \
      "tmux_libs=-lncursesw -ltinfow" \
      "compat_reallocarray=private-api24" \
      "source_date_epoch=$SOURCE_DATE_EPOCH"
    sha256sum "$ROOT/scripts/tmux/android-glob-compat.c" \
      "$ROOT/scripts/tmux/android-glob-compat.h" \
      "$ROOT/scripts/tmux/android-langinfo-compat.c" \
      "$ROOT/scripts/tmux/android-langinfo-compat.h"
  } | sha256sum | awk '{print $1}'
}
BUILD_FINGERPRINT=$(build_fingerprint)

# Rollback restores repository files but intentionally leaves out/ alone.
# Reuse a completed native build only after the canonical runtime seal verifies.
# A pre-fingerprint build from TMUX-01 v20r3 may be adopted exactly once: its
# binary, manifest, and checksum must all exist and verify before the current
# content-addressed fingerprint is written.
if [[ ${CHROOTCTL_TMUX_FORCE_REBUILD:-0} != 1 &&
      -x "$OUT/tmux" &&
      -f "$OUT/tmux-runtime-manifest.json" &&
      -f "$OUT/tmux.sha256" ]]; then
  if [[ -f "$BUILD_FINGERPRINT_FILE" ]]; then
    if [[ $(cat "$BUILD_FINGERPRINT_FILE" 2>/dev/null || true) == "$BUILD_FINGERPRINT" ]] &&
       "$ROOT/scripts/tmux/verify-static-android-arm64.sh" \
         "$OUT/tmux" "$OUT/tmux-runtime-manifest.json"; then
      echo "tmux build cache verified — reusing existing artifact"
      exit 0
    fi
    echo "tmux build cache fingerprint/verifier rejected; rebuilding" >&2
  elif "$ROOT/scripts/tmux/verify-static-android-arm64.sh" \
      "$OUT/tmux" "$OUT/tmux-runtime-manifest.json"; then
    # The verifier checks the manifest and tmux.sha256 against the ELF. Only
    # after that succeeds may an older, otherwise complete build be adopted.
    printf '%s\n' "$BUILD_FINGERPRINT" > "$BUILD_FINGERPRINT_FILE"
    echo "tmux legacy build verified — adopted into current build cache"
    exit 0
  else
    echo "tmux legacy build rejected by runtime verifier; rebuilding" >&2
  fi
fi

rm -rf "$WORK" "$OUT"; mkdir -p "$WORK/src" "$PREFIX" "$OUT"
tar -xzf "$EVENT_TAR" -C "$WORK/src"; tar -xzf "$CURSES_TAR" -C "$WORK/src"; tar -xzf "$TMUX_TAR" -C "$WORK/src"
export CC AR RANLIB STRIP
export CFLAGS="-Os -fPIC -ffile-prefix-map=$WORK=. -fdebug-prefix-map=$WORK=."
export CPPFLAGS="-I$PREFIX/include -I$PREFIX/include/ncursesw"
export LDFLAGS="-L$PREFIX/lib -L$TERMUX_LIB -L$RESOURCE_DIR/lib/linux -static -Wl,--build-id=none"
export PKG_CONFIG_LIBDIR="$PREFIX/lib/pkgconfig"

pushd "$WORK/src/libevent-$LIBEVENT_VERSION" >/dev/null
./configure --host=aarch64-linux-android --prefix="$PREFIX" --disable-shared --enable-static --disable-openssl --disable-samples --disable-libevent-regress --disable-debug-mode CC="$CC" AR="$AR" RANLIB="$RANLIB"
make -j"$JOBS"; make install
popd >/dev/null

pushd "$WORK/src/ncurses-$NCURSES_VERSION" >/dev/null
./configure --host=aarch64-linux-android --prefix="$PREFIX" --without-shared --with-normal --without-debug --without-ada --without-cxx --enable-widec --disable-stripping --with-termlib CC="$CC" AR="$AR" RANLIB="$RANLIB"
make -j"$JOBS" libs; make install.libs install.includes
popd >/dev/null

[[ -f "$PREFIX/lib/libtinfow.a" ]] || { echo "staged static libtinfow.a missing" >&2; exit 1; }

# Prove the property tmux actually needs: the staged split ncurses libraries
# must satisfy real terminfo references when linked with the target compiler.
TERMINFO_PROBE_C="$WORK/terminfo-link-probe.c"
TERMINFO_PROBE="$WORK/terminfo-link-probe"
cat >"$TERMINFO_PROBE_C" <<'EOF'
#include <curses.h>
#include <term.h>
int main(void) {
    int err = 0;
    (void)setupterm((char *)0, 1, &err);
    (void)tigetstr("cup");
    (void)tigetflag("am");
    (void)tigetnum("cols");
    (void)tparm((char *)0, 0L, 0L, 0L, 0L, 0L, 0L, 0L, 0L, 0L);
    (void)del_curterm(cur_term);
    return 0;
}
EOF
# shellcheck disable=SC2086
$CC $CFLAGS $CPPFLAGS "$TERMINFO_PROBE_C" $LDFLAGS \
  -lncursesw -ltinfow -o "$TERMINFO_PROBE" || {
    echo "staged ncursesw/tinfow target link probe failed" >&2
    exit 1
  }
rm -f "$TERMINFO_PROBE_C" "$TERMINFO_PROBE"

# ncurses' minimal install.libs path does not install pkg-config metadata.
# tmux 3.7c falls back to AC_SEARCH_LIBS in that case and its fallback appends
# -lncurses after finding the header, even though this build intentionally
# stages only the wide static archive. Provide target-local ncursesw metadata
# so tmux takes its ncursesw pkg-config path and links only libncursesw.a.
mkdir -p "$PREFIX/lib/pkgconfig"
cat >"$PREFIX/lib/pkgconfig/ncursesw.pc" <<EOF
prefix=$PREFIX
exec_prefix=\${prefix}
libdir=\${exec_prefix}/lib
includedir=\${prefix}/include

Name: ncursesw
Description: staged static wide-character ncurses for chrootctl tmux
Version: $NCURSES_VERSION
Libs: -L\${libdir} -lncursesw -ltinfow
Cflags: -I\${includedir} -I\${includedir}/ncursesw
EOF

# Android/Bionic does not expose glob()/globfree() until API 28. TMUX-01
# intentionally targets API 24, so provide the small source-file glob subset
# used by tmux rather than raising the minimum Android version.
TMUX_CPPFLAGS="$CPPFLAGS"
if (( ANDROID_API < 29 )); then
  # reallocarray is a public Bionic API only from API 29. Keep tmux's compat
  # implementation for API 24, but give it a private symbol name so the NDK
  # static libc's malloc_common.o cannot collide with compat/reallocarray.o.
  TMUX_CPPFLAGS="$TMUX_CPPFLAGS -Dreallocarray=chrootctl_tmux_reallocarray"
fi
TMUX_LIBS="-lncursesw -ltinfow"
# Bionic adds nl_langinfo() in API 26. tmux only asks for CODESET here, so
# retain the API-24 floor with a small compatibility implementation matching
# Bionic's CODESET behavior rather than linking a symbol unavailable at runtime.
if (( ANDROID_API < 26 )); then
  ANDROID_LANGINFO_OBJ="$WORK/android-langinfo-compat.o"
  # shellcheck disable=SC2086
  $CC $CFLAGS -DCHROOTCTL_ANDROID_LANGINFO_COMPAT=1 \
    -I"$ROOT/scripts/tmux" \
    -c "$ROOT/scripts/tmux/android-langinfo-compat.c" -o "$ANDROID_LANGINFO_OBJ"
  TMUX_CPPFLAGS="$TMUX_CPPFLAGS -DCHROOTCTL_ANDROID_LANGINFO_COMPAT=1 -include $ROOT/scripts/tmux/android-langinfo-compat.h"
  TMUX_LIBS="$ANDROID_LANGINFO_OBJ $TMUX_LIBS"
fi
if (( ANDROID_API < 28 )); then
  ANDROID_GLOB_OBJ="$WORK/android-glob-compat.o"
  # shellcheck disable=SC2086
  $CC $CFLAGS -DCHROOTCTL_ANDROID_GLOB_COMPAT=1 \
    -I"$ROOT/scripts/tmux" \
    -c "$ROOT/scripts/tmux/android-glob-compat.c" -o "$ANDROID_GLOB_OBJ"
  TMUX_CPPFLAGS="$TMUX_CPPFLAGS -DCHROOTCTL_ANDROID_GLOB_COMPAT=1 -include $ROOT/scripts/tmux/android-glob-compat.h"
  TMUX_LIBS="$ANDROID_GLOB_OBJ $TMUX_LIBS"
fi

pushd "$WORK/src/tmux-$TMUX_VERSION" >/dev/null
# Bionic exposes forkpty() in <pty.h> from API 23. tmux's AC_SEARCH_LIBS
# probe can false-negative while cross-compiling because it searches host-style
# libraries. Seed the exact Autoconf cache result so tmux defines HAVE_FORKPTY
# and does not enable its incompatible compat/forkpty declaration.
ac_cv_search_forkpty="none required" \
CPPFLAGS="$TMUX_CPPFLAGS" \
./configure --host=aarch64-linux-android --prefix=/data/adb/modules/chrootctl-magisk/runtime/arm64-v8a --enable-static CC="$CC" AR="$AR" RANLIB="$RANLIB" LIBS="$TMUX_LIBS"
make -j"$JOBS"
cp tmux "$OUT/tmux"; "$STRIP" --strip-all "$OUT/tmux"; chmod 0755 "$OUT/tmux"
popd >/dev/null

# Post-link validation is intentionally centralized in
# verify-static-android-arm64.sh.  This producer only writes the binary,
# canonical runtime manifest, and checksum sidecar; it never executes the
# Android target and does not duplicate ELF-policy checks.

sha=$(sha256sum "$OUT/tmux" | awk '{print $1}')
cat > "$OUT/tmux-runtime-manifest.json" <<JSON
{
  "schemaVersion": 1,
  "component": "tmux",
  "version": "$TMUX_VERSION",
  "platform": "android",
  "abi": "arm64-v8a",
  "androidApi": $ANDROID_API,
  "libc": "bionic-static",
  "ndkRevision": "$NDK_REVISION",
  "sourceDateEpoch": "$SOURCE_DATE_EPOCH",
  "linkage": "static",
  "compression": "none",
  "sha256": "$sha",
  "sources": [
    {"name":"tmux","version":"$TMUX_VERSION","url":"https://github.com/tmux/tmux/releases/download/$TMUX_VERSION/tmux-$TMUX_VERSION.tar.gz","sha256":"$TMUX_SHA256"},
    {"name":"libevent","version":"$LIBEVENT_VERSION","url":"https://github.com/libevent/libevent/releases/download/release-$LIBEVENT_VERSION/libevent-$LIBEVENT_VERSION.tar.gz","sha256":"$LIBEVENT_SHA256"},
    {"name":"ncurses","version":"$NCURSES_VERSION","url":"https://ftp.gnu.org/gnu/ncurses/ncurses-$NCURSES_VERSION.tar.gz","sha256":"$NCURSES_SHA256"}
  ]
}
JSON
printf '%s  tmux\n' "$sha" > "$OUT/tmux.sha256"
printf '%s\n' "$BUILD_FINGERPRINT" > "$BUILD_FINGERPRINT_FILE"
printf 'built %s (%s)\n' "$OUT/tmux" "$sha"
