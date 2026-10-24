#!/usr/bin/env bash
set -euo pipefail

# Immutable, reviewed bclone Git commit. Never resolve releases/latest on CI.
readonly BCLONE_REPOSITORY="BenjiThatFoxGuy/bclone"
readonly BCLONE_GIT_URL="https://github.com/${BCLONE_REPOSITORY}.git"
readonly RCLONE_ANDROID_API="26"
readonly RCLONE_ANDROID_ARCH="arm64"
readonly CHROOTCTL_ANDROID_PAGE_SIZE="16384"
readonly CHROOTCTL_REQUIRED_NDK_REVISION="29.0.14206865"

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck source=scripts/rclone-runtime-contract.sh
source "$script_dir/rclone-runtime-contract.sh"
readonly native_page_verifier="$script_dir/verify-native-page-size.go"

fail() {
    local code=$1
    local stage=$2
    shift 2
    printf 'chrootctl bclone runtime install failed [%s]: %s\n' "$stage" "$*" >&2
    exit "$code"
}

run_native_page_verifier() {
    env GOTOOLCHAIN=local go run "$native_page_verifier" "$@"
}

if [[ $# -lt 1 || $# -gt 2 ]]; then
    echo "usage: $0 <jni-output-directory> [ndk-directory]" >&2
    exit 64
fi

# Parse data, never source/eval a lock file.
lock_file="$script_dir/../config/chrootctl/bclone-android-source.lock"
[[ -f "$lock_file" && ! -L "$lock_file" ]] || fail 65 lock 'missing safe reviewed source lock'
lock_value() {
    local key=$1
    awk -F= -v key="$key" '$1==key {print substr($0, length(key)+2)}' "$lock_file"
}
[[ $(lock_value schema) == chrootctl-bclone-source-lock-v1 ]] || fail 65 lock 'unsupported source lock schema'
[[ $(lock_value repository) == "$BCLONE_GIT_URL" ]] || fail 65 lock 'unexpected bclone repository'
[[ $(lock_value ndk_revision) == "$CHROOTCTL_REQUIRED_NDK_REVISION" ]] || fail 65 lock 'unexpected NDK source lock'
[[ $(lock_value android_api) == "$RCLONE_ANDROID_API" ]] || fail 65 lock 'source lock must target API 26'
[[ $(lock_value android_arch) == "$RCLONE_ANDROID_ARCH" ]] || fail 65 lock 'invalid source-lock architecture'
[[ $(lock_value page_size) == "$CHROOTCTL_ANDROID_PAGE_SIZE" ]] || fail 65 lock 'invalid ELF page size'
readonly BCLONE_TAG="$(lock_value tag)"
readonly BCLONE_COMMIT="$(lock_value commit)"
readonly BCLONE_GO_VERSION="$(lock_value go_version)"
[[ "$BCLONE_TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ && "$BCLONE_COMMIT" =~ ^[0-9a-f]{40}$ && "$BCLONE_GO_VERSION" =~ ^go[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail 65 lock 'malformed reviewed source identity'
[[ $(GOTOOLCHAIN=local go version | awk '{print $3}') == "$BCLONE_GO_VERSION" ]] || fail 65 lock "requires reviewed compiler $BCLONE_GO_VERSION"
readonly BCLONE_VERSION="${BCLONE_TAG#v}"

output_root=$1
ndk_root=${2:-${ANDROID_NDK_ROOT:-${ANDROID_NDK_HOME:-}}}
output_dir="$output_root/arm64-v8a"
readonly BCLONE_SOURCE_ARCHIVE="bclone-${BCLONE_COMMIT}.tar.gz"
cache_root="${CHROOTCTL_RCLONE_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/chrootctl/bclone/${BCLONE_COMMIT}-${BCLONE_GO_VERSION}-android-${RCLONE_ANDROID_API}-arm64-16k}"
source_archive="$cache_root/$BCLONE_SOURCE_ARCHIVE"
source_sha_file="$source_archive.sha256"
cached_runtime="$cache_root/rclone"
target="$output_dir/rclone"
tmp_target="$target.tmp.$$"
mkdir -p "$cache_root" "$output_dir"
trap 'rm -f "$tmp_target"' EXIT HUP INT TERM

printf 'chrootctl bclone runtime: pinned source %s @ %s (API 26)\n' "$BCLONE_TAG" "$BCLONE_COMMIT" >&2

fetch_source_archive() {
    local tmp="$source_archive.download.$$" git_dir
    command -v git >/dev/null 2>&1 || fail 69 fetch 'git required to verify source commit'
    git_dir=$(mktemp -d "${TMPDIR:-$cache_root}/bclone-git.XXXXXX") || fail 70 fetch 'cannot allocate Git source checkout'
    rm -f "$tmp"
    git -C "$git_dir" init -q || fail 69 fetch 'cannot initialize source checkout'
    git -C "$git_dir" remote add origin "$BCLONE_GIT_URL"
    git -C "$git_dir" fetch --depth=1 origin "refs/tags/$BCLONE_TAG" || fail 69 fetch 'cannot fetch pinned bclone tag'
    [[ $(git -C "$git_dir" rev-parse 'FETCH_HEAD^{commit}') == "$BCLONE_COMMIT" ]] || fail 65 source 'upstream tag does not resolve to reviewed source commit'
    git -C "$git_dir" checkout -q --detach "$BCLONE_COMMIT" || fail 65 source 'cannot check out pinned commit'
    git -C "$git_dir" archive --format=tar.gz --prefix="bclone-${BCLONE_TAG}/" --output="$tmp" HEAD || fail 69 source 'cannot archive pinned Git tree'
    rm -rf "$git_dir"
    [[ -s "$tmp" ]] || fail 69 source 'empty bclone Git archive'
    run_native_page_verifier archive-safe "$tmp" >/dev/null || fail 65 source 'unsafe bclone archive contents'
    mv -f "$tmp" "$source_archive"
    sha256sum "$source_archive" | awk '{print $1}' > "$source_sha_file.tmp.$$"
    mv -f "$source_sha_file.tmp.$$" "$source_sha_file"
}

validate_cached_source_archive() {
    local expected actual
    [[ -s "$source_archive" && -s "$source_sha_file" ]] || return 1
    expected=$(tr -d '[:space:]' < "$source_sha_file")
    [[ "$expected" =~ ^[0-9a-fA-F]{64}$ ]] || return 1
    actual=$(sha256sum "$source_archive" | awk '{print $1}')
    [[ "$actual" == "$expected" ]] || return 1
    run_native_page_verifier archive-safe "$source_archive" >/dev/null || return 1
}

ensure_source_archive() {
    if ! validate_cached_source_archive; then
        if [[ -e "$source_archive" || -e "$source_sha_file" ]]; then
            printf 'chrootctl bclone runtime: cached source integrity mismatch; refetching %s\n' "$BCLONE_TAG" >&2
            rm -f "$source_archive" "$source_sha_file"
        fi
        fetch_source_archive
    fi
    printf 'chrootctl bclone runtime: source archive integrity verified for %s\n' "$BCLONE_TAG" >&2
}

validate_runtime() {
    local runtime=$1
    local build_info version_output
    [[ -s "$runtime" ]] || return 1
    run_native_page_verifier elf --min-page-size "$CHROOTCTL_ANDROID_PAGE_SIZE" "$runtime" >/dev/null || return 1
    build_info=$(go version -m "$runtime" 2>&1) || return 1
    chrootctl_rclone_validate_build_info "$build_info" || return 1
    if [[ -d /system && -e /system/bin/linker64 ]]; then
        version_output=$("$runtime" version 2>&1) || return 1
        chrootctl_rclone_validate_version_output "$version_output" "$BCLONE_VERSION" || return 1
    fi
}

if validate_runtime "$cached_runtime" && [[ -s "$cache_root/rclone-build-receipt.json" ]]; then
    expected_cached_sha=$(sha256sum "$cached_runtime" | awk '{print $1}')
    if ! grep -Fq "\"sha256\":\"$expected_cached_sha\"" "$cache_root/rclone-build-receipt.json"; then
        fail 65 cache 'cached rclone build receipt hash mismatch'
    fi
    printf 'chrootctl bclone runtime: using verified 16 KiB cache %s\n' "$cached_runtime" >&2
    cp -f "$cached_runtime" "$tmp_target"
    chmod 0755 "$tmp_target"
    mv -f "$tmp_target" "$target"
    cp -f "$cache_root/rclone-build-receipt.json" "$output_dir/rclone-build-receipt.json"
    trap - EXIT HUP INT TERM
    printf 'chrootctl bclone runtime: packaged cached %s -> %s\n' "$BCLONE_TAG" "$target" >&2
    exit 0
fi
rm -f "$cached_runtime"

ensure_source_archive

toolchain_cc=""
toolchain_cxx=""
toolchain_lane=""
shim_paths=()
work_dir=""

# A shell can hide an execve(ENOENT) from a script with an unusable shebang,
# so --version alone is not authoritative on Termux. Every candidate lane is
# accepted only after Go/cgo itself compiles and externally links an Android PIE.
compiler_exec_without_termux_exec() {
    local compiler=$1
    env -u LD_PRELOAD "$compiler" --version >/dev/null 2>&1
}

make_bash_script_shim() {
    local actual=$1
    local label=$2
    local bash_bin shim_dir shim tmp key
    bash_bin=$(command -v bash) || return 1
    shim_dir="$cache_root/toolchain-shims"
    mkdir -p "$shim_dir"
    key=$(printf '%s' "$actual" | sha256sum | awk '{print substr($1,1,16)}')
    shim="$shim_dir/${label}-${key}.sh"
    tmp="$shim.tmp.$$"
    {
        printf '#!%s\n' "$bash_bin"
        printf 'exec %q %q "$@"\n' "$bash_bin" "$actual"
    } > "$tmp"
    chmod 0700 "$tmp"
    mv -f "$tmp" "$shim"
    shim_paths+=("$shim")
    printf '%s\n' "$shim"
}

# On an Android/Termux host the NDK host clang binary can exist but be
# unlaunchable because its glibc interpreter is unavailable. In that case use
# Termux's native clang (a real Android executable) while keeping the NDK r29
# target triple + sysroot. This preserves Android API/ABI linkage without asking
# cgo to execute a glibc-hosted NDK compiler.
make_termux_ndk_sysroot_shim() {
    local native_compiler=$1
    local sysroot=$2
    local label=$3
    local bash_bin shim_dir shim tmp key target_triple
    bash_bin=$(command -v bash) || return 1
    target_triple="aarch64-linux-android${RCLONE_ANDROID_API}"
    shim_dir="$cache_root/toolchain-shims"
    mkdir -p "$shim_dir"
    key=$(printf '%s|%s|%s' "$native_compiler" "$sysroot" "$target_triple" | sha256sum | awk '{print substr($1,1,16)}')
    shim="$shim_dir/${label}-${key}.sh"
    tmp="$shim.tmp.$$"
    {
        printf '#!%s\n' "$bash_bin"
        printf 'exec %q --target=%q --sysroot=%q "$@"\n' "$native_compiler" "$target_triple" "$sysroot"
    } > "$tmp"
    chmod 0700 "$tmp"
    mv -f "$tmp" "$shim"
    shim_paths+=("$shim")
    printf '%s\n' "$shim"
}

probe_root=$(mktemp -d "${TMPDIR:-$cache_root}/chrootctl-rclone-cgo-probes.XXXXXX")
cleanup() {
    rm -f "$tmp_target"
    rm -rf "$probe_root"
    [[ -z "$work_dir" ]] || rm -rf "$work_dir"
}
trap cleanup EXIT HUP INT TERM

cat > "$probe_root/probe.go" <<'GO'
package main
/*
static int chrootctl_add(int a, int b) { return a + b; }
*/
import "C"
func main() { _ = C.chrootctl_add(20, 22) }
GO

probe_toolchain_candidate() {
    local candidate_cc=$1
    local candidate_cxx=$2
    local lane=$3
    local safe_lane probe_out probe_log probe_ldflags

    safe_lane=$(printf '%s' "$lane" | tr -c 'A-Za-z0-9._-' '_')
    probe_out="$probe_root/${safe_lane}.elf"
    probe_log="$probe_root/${safe_lane}.log"
    rm -f "$probe_out" "$probe_log"

    printf 'chrootctl rclone runtime: probing compiler lane %s\n' "$lane" >&2
    printf 'chrootctl rclone runtime: probe compiler %s\n' "$candidate_cc" >&2

    probe_ldflags="-s -w -linkmode=external -extldflags=-Wl,-z,max-page-size=${CHROOTCTL_ANDROID_PAGE_SIZE},-z,common-page-size=${CHROOTCTL_ANDROID_PAGE_SIZE}"
    if (
        cd "$probe_root"
        export GOOS=android GOARCH=arm64 CGO_ENABLED=1 GOTOOLCHAIN=local
        export CC="$candidate_cc" CC_FOR_TARGET="$candidate_cc"
        if [[ -n "$candidate_cxx" ]]; then
            export CXX="$candidate_cxx"
        else
            unset CXX || true
        fi
        export CGO_CFLAGS="-O2 -fPIC"
        export CGO_LDFLAGS="-fuse-ld=lld -Wl,-z,max-page-size=${CHROOTCTL_ANDROID_PAGE_SIZE} -Wl,-z,common-page-size=${CHROOTCTL_ANDROID_PAGE_SIZE}"
        env -u LD_PRELOAD go build \
            -trimpath \
            -buildvcs=false \
            -buildmode=pie \
            -ldflags "$probe_ldflags" \
            -o "$probe_out" \
            "$probe_root/probe.go"
    ) >"$probe_log" 2>&1 && \
        run_native_page_verifier elf --min-page-size "$CHROOTCTL_ANDROID_PAGE_SIZE" "$probe_out" >/dev/null 2>&1
    then
        toolchain_cc=$candidate_cc
        toolchain_cxx=$candidate_cxx
        toolchain_lane=$lane
        printf 'chrootctl rclone runtime: compiler lane %s accepted by Go/cgo + 16 KiB probe\n' "$lane" >&2
        return 0
    fi

    printf 'chrootctl rclone runtime: compiler lane %s rejected by Go/cgo + 16 KiB probe; trying next candidate\n' "$lane" >&2
    if [[ -s "$probe_log" ]]; then
        printf '%s\n' '--- compiler probe tail ---' >&2
        tail -n 12 "$probe_log" >&2 || true
        printf '%s\n' '--- end compiler probe tail ---' >&2
    fi
    return 1
}

try_candidate() {
    local candidate_cc=$1
    local candidate_cxx=${2:-}
    local lane=$3
    [[ -e "$candidate_cc" ]] || return 1
    probe_toolchain_candidate "$candidate_cc" "$candidate_cxx" "$lane"
}

select_toolchain() {
    local candidate candidate_cxx shim shim_cxx triple sysroot native_cc native_cxx

    if [[ -n "${CHROOTCTL_RCLONE_CC:-}" ]]; then
        candidate=$CHROOTCTL_RCLONE_CC
        if command -v "$candidate" >/dev/null 2>&1; then
            candidate=$(command -v "$candidate")
        fi
        candidate_cxx="${CHROOTCTL_RCLONE_CXX:-}"
        if [[ -n "$candidate_cxx" ]] && command -v "$candidate_cxx" >/dev/null 2>&1; then
            candidate_cxx=$(command -v "$candidate_cxx")
        fi
        if try_candidate "$candidate" "$candidate_cxx" "override-direct"; then
            return 0
        fi
        shim=$(make_bash_script_shim "$candidate" "override-cc") || shim=""
        shim_cxx=""
        if [[ -n "$candidate_cxx" && -e "$candidate_cxx" ]]; then
            shim_cxx=$(make_bash_script_shim "$candidate_cxx" "override-cxx") || shim_cxx=""
        fi
        if [[ -n "$shim" ]] && try_candidate "$shim" "$shim_cxx" "override-bash-shim"; then
            return 0
        fi
        printf 'chrootctl rclone runtime: CHROOTCTL_RCLONE_CC override was unusable; continuing with managed candidates\n' >&2
    fi

    if [[ -n "$ndk_root" && -d "$ndk_root" ]]; then
        local revision=""
        if [[ -f "$ndk_root/source.properties" ]]; then
            revision=$(sed -n 's/^[[:space:]]*Pkg\.Revision[[:space:]]*=[[:space:]]*//p' "$ndk_root/source.properties" | head -n1)
        fi
        if [[ -n "$revision" && "$revision" != "$CHROOTCTL_REQUIRED_NDK_REVISION" ]]; then
            printf 'chrootctl rclone runtime: Gradle supplied NDK %s; expected %s\n' "$revision" "$CHROOTCTL_REQUIRED_NDK_REVISION" >&2
        fi

        while IFS= read -r candidate; do
            [[ -e "$candidate" ]] || continue
            candidate_cxx="${candidate%-clang}-clang++"
            [[ -e "$candidate_cxx" ]] || candidate_cxx=""
            if try_candidate "$candidate" "$candidate_cxx" "ndk-direct"; then
                return 0
            fi

            # Feed NDK shell wrappers to Termux Bash as data. If the wrapper then
            # reaches an unlaunchable glibc clang binary, the Go/cgo probe rejects
            # this lane and selection continues instead of aborting.
            shim=$(make_bash_script_shim "$candidate" "ndk-cc") || shim=""
            shim_cxx=""
            if [[ -n "$candidate_cxx" ]]; then
                shim_cxx=$(make_bash_script_shim "$candidate_cxx" "ndk-cxx") || shim_cxx=""
            fi
            if [[ -n "$shim" ]] && try_candidate "$shim" "$shim_cxx" "ndk-termux-bash-shim"; then
                return 0
            fi
        done < <(find "$ndk_root/toolchains/llvm/prebuilt" \( -type f -o -type l \) -name "aarch64-linux-android${RCLONE_ANDROID_API}-clang" 2>/dev/null | sort)

        # Preferred Termux fallback: execute the native Termux clang but point it
        # at the exact Gradle-selected NDK sysroot and Android API target.
        native_cc=$(command -v clang 2>/dev/null || true)
        native_cxx=$(command -v clang++ 2>/dev/null || true)
        if [[ -n "$native_cc" ]]; then
            while IFS= read -r sysroot; do
                [[ -d "$sysroot" ]] || continue
                shim=$(make_termux_ndk_sysroot_shim "$native_cc" "$sysroot" "termux-ndk-cc") || shim=""
                shim_cxx=""
                if [[ -n "$native_cxx" ]]; then
                    shim_cxx=$(make_termux_ndk_sysroot_shim "$native_cxx" "$sysroot" "termux-ndk-cxx") || shim_cxx=""
                fi
                if [[ -n "$shim" ]] && try_candidate "$shim" "$shim_cxx" "termux-native-clang-ndk-sysroot"; then
                    return 0
                fi
            done < <(find "$ndk_root/toolchains/llvm/prebuilt" -mindepth 2 -maxdepth 2 -type d -name sysroot 2>/dev/null | sort)
        fi
    fi

    # Final fallback: Termux clang already targets Android/aarch64. It is accepted
    # only if the same real CGO + PIE + 16 KiB probe succeeds.
    if command -v clang >/dev/null 2>&1; then
        candidate=$(command -v clang)
        triple=$(env -u LD_PRELOAD "$candidate" -dumpmachine 2>/dev/null || true)
        if [[ "$triple" == aarch64* && "$triple" == *android* ]]; then
            candidate_cxx=$(command -v clang++ 2>/dev/null || true)
            if try_candidate "$candidate" "$candidate_cxx" "termux-native-clang"; then
                return 0
            fi
        fi
    fi
    return 1
}

select_toolchain || fail 69 toolchain \
    'no compiler lane passed the Go/cgo Android/arm64 + 16 KiB execution probe'
cc=$toolchain_cc
cxx=$toolchain_cxx
printf 'chrootctl rclone runtime: selected compiler lane %s\n' "$toolchain_lane" >&2
printf 'chrootctl rclone runtime: selected compiler %s\n' "$cc" >&2
rm -rf "$probe_root"
probe_root=""

work_dir=$(mktemp -d "${TMPDIR:-$cache_root}/chrootctl-bclone-source-build.XXXXXX")
printf 'chrootctl bclone runtime: extracting pinned source %s\n' "$BCLONE_TAG" >&2
run_native_page_verifier archive-safe "$source_archive" >/dev/null || \
    fail 65 source 'bclone source archive contains an unsafe path'
tar -xzf "$source_archive" -C "$work_dir" || fail 65 source 'could not extract bclone source archive'
source_dir=$(find "$work_dir" -mindepth 1 -maxdepth 1 -type d -name 'bclone-*' -print -quit)
[[ -n "$source_dir" && -f "$source_dir/go.mod" ]] || \
    fail 65 source 'bclone source archive layout is incomplete'
if ! grep -Eq '^module[[:space:]]+github\.com/rclone/rclone[[:space:]]*$' "$source_dir/go.mod"; then
    fail 65 identity 'bclone no longer exposes the expected github.com/rclone/rclone module identity'
fi

jobs=${CHROOTCTL_RCLONE_BUILD_JOBS:-1}
[[ "$jobs" =~ ^[1-9][0-9]*$ ]] || fail 64 build 'CHROOTCTL_RCLONE_BUILD_JOBS must be a positive integer'

# GitHub's bclone releases do not ship rclone's separate vendor tarball. Vendor
# the exact resolved release before the build; go.sum remains authoritative for
# dependency checksums, and the subsequent build is forced through -mod=vendor.
printf 'chrootctl bclone runtime: vendoring dependencies for %s\n' "$BCLONE_TAG" >&2
(
    cd "$source_dir"
    export GOTOOLCHAIN=local
    export GOMODCACHE="$cache_root/go-module-cache"
    mkdir -p "$GOMODCACHE"
    go mod vendor
) || fail 69 vendor 'could not vendor dependencies for the reviewed bclone release'
[[ -d "$source_dir/vendor" && -f "$source_dir/vendor/modules.txt" ]] || \
    fail 65 vendor 'bclone dependency vendoring did not produce vendor/modules.txt'

ldflags="-s -w -X github.com/rclone/rclone/fs.Version=v${BCLONE_VERSION} -linkmode=external -extldflags=-Wl,-z,max-page-size=${CHROOTCTL_ANDROID_PAGE_SIZE},-z,common-page-size=${CHROOTCTL_ANDROID_PAGE_SIZE}"

printf 'chrootctl bclone runtime: building %s for android/arm64 (16 KiB)\n' "$BCLONE_TAG" >&2
(
    cd "$source_dir"
    export GOOS=android
    export GOARCH=arm64
    export CGO_ENABLED=1
    export GOTOOLCHAIN=local
    export CC="$cc"
    export CC_FOR_TARGET="$cc"
    if [[ -n "$cxx" ]]; then
        export CXX="$cxx"
    else
        unset CXX || true
    fi
    export CGO_CFLAGS="-O2 -fPIC"
    export CGO_LDFLAGS="-fuse-ld=lld -Wl,-z,max-page-size=${CHROOTCTL_ANDROID_PAGE_SIZE} -Wl,-z,common-page-size=${CHROOTCTL_ANDROID_PAGE_SIZE}"
    export GOCACHE="$work_dir/go-build-cache"
    export GOMODCACHE="$cache_root/go-module-cache"
    mkdir -p "$GOCACHE" "$GOMODCACHE"
    go build -mod=vendor -p "$jobs" -tags "android noselfupdate" -trimpath -buildvcs=false -buildmode=pie \
        -ldflags "$ldflags" -o "$tmp_target" .
) || fail 70 build 'bclone Android/arm64 source build failed'
chmod 0755 "$tmp_target"

printf 'chrootctl bclone runtime: validating AArch64 PIE, rclone-compatible identity and 16 KiB PT_LOAD alignment\n' >&2
run_native_page_verifier runtime \
    --min-page-size "$CHROOTCTL_ANDROID_PAGE_SIZE" \
    --version "$BCLONE_VERSION" \
    "$tmp_target" || fail 65 elf 'bclone-backed rclone runtime failed ELF/version/16 KiB validation'
build_info=$(go version -m "$tmp_target" 2>&1) || {
    printf '%s\n' "$build_info" >&2
    fail 66 build-info 'could not inspect bclone Go build metadata'
}
if ! chrootctl_rclone_validate_build_info "$build_info"; then
    printf '%s\n' "$build_info" >&2
    fail 65 build-info 'bclone runtime build metadata is not the required Android/ARM64/CGO shape'
fi

if [[ -d /system && -e /system/bin/linker64 ]]; then
    printf 'chrootctl bclone runtime: executing on-host version smoke test\n' >&2
    version_output=$("$tmp_target" version 2>&1) || {
        printf '%s\n' "$version_output" >&2
        fail 66 execute 'bclone Android runtime failed its on-host version smoke test'
    }
    if ! chrootctl_rclone_validate_version_output "$version_output" "$BCLONE_VERSION"; then
        printf '%s\n' "$version_output" >&2
        fail 65 identity 'unexpected bclone-backed rclone version output'
    fi
fi

cp -f "$tmp_target" "$cached_runtime"
chmod 0755 "$cached_runtime"
artifact_sha=$(sha256sum "$tmp_target" | awk '{print $1}')
printf '{"schemaVersion":1,"sourceCommit":"%s","androidApi":26,"pageSize":16384,"sha256":"%s"}\n' "$BCLONE_COMMIT" "$artifact_sha" > "$cache_root/rclone-build-receipt.json.tmp.$$"
mv -f "$cache_root/rclone-build-receipt.json.tmp.$$" "$cache_root/rclone-build-receipt.json"
mv -f "$tmp_target" "$target"
cp -f "$cache_root/rclone-build-receipt.json" "$output_dir/rclone-build-receipt.json"
rm -rf "$work_dir"
work_dir=""
trap - EXIT HUP INT TERM
printf 'chrootctl bclone runtime: packaged source-built 16 KiB %s -> %s\n' "$BCLONE_TAG" "$target" >&2
