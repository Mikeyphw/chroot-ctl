#!/usr/bin/env bash
# CC14: prove the GitHub-hosted and Termux module paths can invoke checked-in
# POSIX-readable bash scripts even when their Git file mode is 100644.
set -euo pipefail
SOURCE_ROOT=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
T=$(mktemp -d "${TMPDIR:-/tmp}/chrootctl-cc14-shell.XXXXXXXX")
trap 'rm -rf -- "$T"' EXIT
mkdir -p "$T/scripts/ci" "$T/scripts/tmux" "$T/scripts/devtool" \
  "$T/out/tmux/arm64-v8a" "$T/out/module/runtime/arm64-v8a" \
  "$T/sdk/ndk/29.0.14206865/toolchains/llvm/prebuilt/linux-x86_64/bin"
cp "$SOURCE_ROOT/scripts/ci/hosted-release-stage.sh" "$T/scripts/ci/hosted-release-stage.sh"
cp "$SOURCE_ROOT/scripts/ci/require-hosted-ndk.sh" "$T/scripts/ci/require-hosted-ndk.sh"
cp "$SOURCE_ROOT/scripts/devtool/root-module-stage.sh" "$T/scripts/devtool/root-module-stage.sh"
chmod 755 "$T/scripts/ci/require-hosted-ndk.sh"
cat > "$T/scripts/tmux/verify-static-android-arm64.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
[[ $# == 2 ]]
[[ "$1" == "${TEST_ROOT}/out/tmux/arm64-v8a/tmux" ]]
[[ "$2" == "${TEST_ROOT}/out/tmux/arm64-v8a/tmux-runtime-manifest.json" ]]
printf 'verify-ok\n' >> "$TEST_ROOT/verified"
SH
cat > "$T/scripts/install-rclone-android-runtime.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == "$TEST_ROOT/out/rclone" ]]
[[ "$2" == "$TEST_ROOT/sdk/ndk/29.0.14206865" ]]
[[ "$CHROOTCTL_RCLONE_CC" == "$2/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android26-clang" ]]
printf 'rclone-ok\n' >> "$TEST_ROOT/verified"
SH
chmod 644 "$T/scripts/tmux/verify-static-android-arm64.sh" "$T/scripts/install-rclone-android-runtime.sh"
export TEST_ROOT="$T"
# A direct invocation must reproduce the old permission failure in our fixture.
if "$T/scripts/tmux/verify-static-android-arm64.sh" x y >/dev/null 2>&1; then
  echo 'FAIL_CC14_TEST_SCRIPT_UNEXPECTEDLY_EXECUTABLE' >&2; exit 1
fi
# The historical failure: verifier was source-tracked 100644, so direct exec
# generated exit 126 on GitHub even though the preceding tmux build succeeded.
bash "$T/scripts/ci/hosted-release-stage.sh" verify-tmux
[[ $(cat "$T/verified") == verify-ok ]]
# Prove the second consumer is independent of the verifier's executable bit.
CHROOTCTL_TMUX_OUTPUT="$T/out/tmux/arm64-v8a" bash "$T/scripts/devtool/root-module-stage.sh" build-tmux-verify
[[ $(wc -l < "$T/verified") == 2 ]]
# Prevent the next identical permission failure at the bclone/rclone stage.
NDK="$T/sdk/ndk/29.0.14206865"
printf 'Pkg.Revision = 29.0.14206865\n' > "$NDK/source.properties"
CC="$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android26-clang"
printf '#!/bin/sh\nexit 0\n' > "$CC"
chmod 755 "$CC"
ANDROID_HOME="$T/sdk" ANDROID_NDK_HOME="$T/incorrect" ANDROID_NDK_ROOT="$T/incorrect" \
  bash "$T/scripts/ci/hosted-release-stage.sh" build-rclone
[[ $(tail -n 1 "$T/verified") == rclone-ok ]]
# No call site may rely on an executable bit for the read-only tmux verifier.
[[ $(grep -Fc 'bash scripts/tmux/verify-static-android-arm64.sh ' "$SOURCE_ROOT/scripts/devtool/root-module-stage.sh") == 2 ]]
printf '%s\n' PASS_CC14_NONEXECUTABLE_TMUX_VERIFIER_AND_RCLONE_STAGE
