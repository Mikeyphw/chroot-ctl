#!/usr/bin/env bash
# Require the explicit, source-locked Android NDK installed by hosted Actions.
# stdout is exclusively the canonical approved NDK directory.
set -euo pipefail
[[ $# == 3 ]] || { echo 'usage: require-hosted-ndk.sh SDK_ROOT NDK_REVISION ANDROID_API' >&2; exit 64; }
sdk_root=$1
revision=$2
api=$3
[[ -n $sdk_root && -d $sdk_root ]] || { echo "FAIL_HOSTED_NDK: Android SDK directory missing: $sdk_root" >&2; exit 1; }
[[ $revision =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && $api == 26 ]] || {
  echo "FAIL_HOSTED_NDK: invalid locked revision/API: $revision / $api" >&2; exit 1;
}
# An inherited ANDROID_NDK_HOME/ANDROID_NDK_ROOT must never choose the build toolchain.
# GitHub Actions explicitly installed this exact side-by-side path.
ndk_dir="$sdk_root/ndk/$revision"
props="$ndk_dir/source.properties"
[[ -f $props && -r $props && ! -L $props ]] || {
  echo "FAIL_HOSTED_NDK: missing/unreadable source.properties at $props" >&2; exit 1;
}
# Parse a *single* Pkg.Revision, normalizing CRLF and benign surrounding whitespace,
# but never accepting a different revision, a partial match or two revision entries.
observed=$(LC_ALL=C awk -F= '
  $1 ~ /^[[:space:]]*Pkg[.]Revision[[:space:]]*$/ {
    value=$2
    gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
    if (length(value) == 0) exit 2
    count++
    revision=value
  }
  END { if (count != 1) exit 2; print revision }
' "$props") || {
  echo "FAIL_HOSTED_NDK: missing/duplicate malformed Pkg.Revision at $props" >&2; exit 1;
}
[[ $observed == "$revision" ]] || {
  echo "FAIL_HOSTED_NDK: NDK revision differs: expected=$revision actual=$observed path=$props" >&2; exit 1;
}
compiler="$ndk_dir/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android${api}-clang"
[[ -f $compiler && -x $compiler && ! -L $compiler ]] || {
  echo "FAIL_HOSTED_NDK: locked API $api arm64 compiler missing: $compiler" >&2; exit 1;
}
# Prevent a symlinked side-by-side NDK from escaping the reviewed SDK tree.
[[ ! -L $ndk_dir ]] || { echo "FAIL_HOSTED_NDK: linked NDK root refused: $ndk_dir" >&2; exit 1; }
printf '%s\n' "$ndk_dir"
