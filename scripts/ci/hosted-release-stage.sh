#!/usr/bin/env bash
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
cd "$ROOT"
readonly STAGE=${1:-}
readonly DEVTOOL_ROOT=${CHROOTCTL_DEVTOOL_ROOT:-}
readonly NDK_REV=29.0.14206865
readonly API=26
readonly DUAL_ROOT="$ROOT/out/dual-release"
readonly TMUX_ROOT="$ROOT/out/tmux/arm64-v8a"
readonly RCLONE_ROOT="$ROOT/out/rclone/arm64-v8a"
readonly TOOL_ROOT="$ROOT/out/hosted-evidence"
lock_get() { awk -F= -v k="$1" '$1==k {print substr($0,length(k)+2)}' "$2"; }
failed() { echo "FAIL_HOSTED_RELEASE_${STAGE}: $*" >&2; exit 1; }
ensure_ndk() {
  : "${ANDROID_HOME:?Android SDK required}"
  # Never accept a runner- or Devtool-inherited NDK_HOME as build authority.
  # Select and validate the side-by-side NDK installed in the pinned SDK slot.
  local pinned_ndk
  pinned_ndk=$(scripts/ci/require-hosted-ndk.sh "$ANDROID_HOME" "$NDK_REV" "$API") || failed 'locked API 26 Android NDK validation failed'
  export ANDROID_NDK_HOME="$pinned_ndk" ANDROID_NDK_ROOT="$pinned_ndk"
  CC="$pinned_ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android${API}-clang"
  echo "PASS_HOSTED_NDK_LOCK revision=$NDK_REV api=$API source=$pinned_ndk/source.properties" >&2
  export CHROOTCTL_ANDROID_CC="$CC" CHROOTCTL_RCLONE_CC="$CC"
}
case "$STAGE" in
  preflight)
    [[ -n "$DEVTOOL_ROOT" && -d "$DEVTOOL_ROOT/.git" ]] || failed 'reviewed Devtool checkout required'
    [[ $(lock_get schema config/chrootctl/devtool-hosted-source.lock) == chrootctl-devtool-hosted-source-v1 ]] || failed 'Devtool source lock schema'
    [[ $(lock_get repository config/chrootctl/devtool-hosted-source.lock) == Mikeyphw/devtool ]] || failed 'Devtool repository lock'
    [[ $(git -C "$DEVTOOL_ROOT" rev-parse HEAD) == "$(lock_get commit config/chrootctl/devtool-hosted-source.lock)" ]] || failed 'Devtool checkout differs from source lock'
    [[ $(git -C "$DEVTOOL_ROOT" status --porcelain) == '' ]] || failed 'Devtool checkout is dirty'
    [[ $(git rev-parse HEAD) == "${CHROOTCTL_EXPECTED_SOURCE_SHA:-}" ]] || failed 'Chrootctl checkout differs from requested source commit'
    [[ $(git status --porcelain) == '' ]] || failed 'Chrootctl checkout is dirty'
    [[ "${CHROOTCTL_EXPECTED_DEVTOOL_SHA:-}" == "$(lock_get commit config/chrootctl/devtool-hosted-source.lock)" ]] || failed 'Devtool expected revision mismatch'
    [[ $(go version | awk '{print $3}') == "$(lock_get go_version config/chrootctl/bclone-android-source.lock)" ]] || failed 'reviewed Go compiler required'
    [[ $(lock_get android_api config/chrootctl/bclone-android-source.lock) == 26 ]] || failed 'API 26 source lock required'
    ensure_ndk
    [[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || failed 'hosted release requires Linux x86_64'
    echo 'PASS_HOSTED_SOURCE_NDK_API26_GO_DEVTOOL_LOCK'
    ;;
  restore-go)
    GOTOOLCHAIN=local go mod download
    GOTOOLCHAIN=local go mod verify
    ;;
  restore-tmux)
    CHROOTCTL_TMUX_FETCH_ONLY=1 scripts/tmux/build-static-android-arm64.sh
    ;;
  build-tmux)
    ensure_ndk
    CHROOTCTL_TMUX_HOSTED_NDK=1 scripts/tmux/build-static-android-arm64.sh
    ;;
  verify-tmux)
    scripts/tmux/verify-static-android-arm64.sh "$TMUX_ROOT/tmux" "$TMUX_ROOT/tmux-runtime-manifest.json"
    ;;
  build-rclone)
    ensure_ndk
    CHROOTCTL_RCLONE_CACHE_DIR="${CHROOTCTL_RCLONE_CACHE_DIR:-$ROOT/.devtool/cache/rclone-runtime}" \
      scripts/install-rclone-android-runtime.sh "$ROOT/out/rclone" "$ANDROID_NDK_HOME"
    ;;
  build-repoctl)
    mkdir -p out
    GOTOOLCHAIN=local go build -trimpath -o out/repoctl-devtool ./cmd/repoctl
    ;;
  test-webui|test-go|test-tmux|lint-native|lint-go)
    map="${STAGE/lint-native/lint-native}"
    scripts/devtool/root-module-stage.sh "$map"
    ;;
  test-verifier)
    bash scripts/ci/test-require-hosted-ndk.sh
    GOTOOLCHAIN=local go test -count=1 scripts/ci/verify-dual-release.go scripts/ci/verify-dual-release_test.go
    GOTOOLCHAIN=local go test -count=1 scripts/ci/verify-devtool-receipt.go scripts/ci/verify-devtool-receipt_test.go
    GOTOOLCHAIN=local go test -count=1 scripts/ci/reconcile-qualification.go scripts/ci/reconcile-qualification_test.go
    sh -n scripts/device/cc09-module-snapshot.sh
    bash scripts/ci/test-finalize-hosted-evidence.sh
    ;;
  test-skybind-consumer)
    GOTOOLCHAIN=local go test -count=1 ./internal/skybindr1 -run 'TestCC08'
    GOTOOLCHAIN=local go run ./cmd/devtoolgates r1
    ;;
  test-edition-upgrade)
    GOTOOLCHAIN=local go test -count=1 ./internal/module -run 'TestCC09'
    ;;
  test-source)
    go run ./cmd/devtoolgates actions
    go run ./cmd/devtoolgates r1
    out/repoctl-devtool validate
    ;;
  build-editions)
    ensure_ndk
    [[ -s "$RCLONE_ROOT/rclone-build-receipt.json" ]] || failed 'rclone source receipt missing'
    [[ -x "$TMUX_ROOT/tmux" && -x "$RCLONE_ROOT/rclone" ]] || failed 'native dependencies missing'
    CHROOTCTL_TMUX_PATH="$TMUX_ROOT/tmux" CHROOTCTL_REQUIRE_TMUX=1 \
    CHROOTCTL_RCLONE_PATH="$RCLONE_ROOT/rclone" \
      out/repoctl-devtool build-editions --output-root "$DUAL_ROOT" \
        --rclone "$RCLONE_ROOT/rclone" --jobs "${DEVTOOL_MAX_WORKERS:-2}"
    ;;
  verify-editions)
    GOTOOLCHAIN=local go run scripts/ci/verify-dual-release.go --root "$DUAL_ROOT" --source "$CHROOTCTL_EXPECTED_SOURCE_SHA" --devtool "$CHROOTCTL_EXPECTED_DEVTOOL_SHA"
    ;;
  receipt)
    GOTOOLCHAIN=local go run scripts/ci/verify-dual-release.go --root "$DUAL_ROOT" --source "$CHROOTCTL_EXPECTED_SOURCE_SHA" --devtool "$CHROOTCTL_EXPECTED_DEVTOOL_SHA" --publish "$TOOL_ROOT"
    GOTOOLCHAIN=local go run scripts/ci/reconcile-qualification.go \
      --hosted-evidence "$TOOL_ROOT" --output "$TOOL_ROOT/release-qualification.json"
    # Context is informative, not an independently signed attestation. The
    # Devtool machine receipt and optional GitHub Sigstore record remain distinct.
    ndk_identity=$(sha256sum "$ANDROID_HOME/ndk/$NDK_REV/source.properties" | awk '{print $1}')
    bclone_lock=$(sha256sum config/chrootctl/bclone-android-source.lock | awk '{print $1}')
    devtool_lock=$(sha256sum config/chrootctl/devtool-hosted-source.lock | awk '{print $1}')
    source_tree=$(git rev-parse HEAD^{tree})
    cat > "$TOOL_ROOT/build-context.json" <<EOF
{"schemaVersion":1,"androidApi":26,"sourceCommit":"$CHROOTCTL_EXPECTED_SOURCE_SHA","sourceTree":"$source_tree","devtoolCommit":"$CHROOTCTL_EXPECTED_DEVTOOL_SHA","bcloneLockSHA256":"$bclone_lock","devtoolLockSHA256":"$devtool_lock","ndkSourcePropertiesSHA256":"$ndk_identity","goCompiler":"$(go version | awk '{print $3}')","githubRunId":"${GITHUB_RUN_ID:-}","githubRunAttempt":"${GITHUB_RUN_ATTEMPT:-}"}
EOF
    (cd "$TOOL_ROOT" && sha256sum release-evidence.json release-qualification.json build-context.json >> SHA256SUMS)
    ;;
  *) failed 'unknown/non-permitted stage' ;;
esac
