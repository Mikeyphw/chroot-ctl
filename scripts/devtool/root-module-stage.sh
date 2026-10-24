#!/usr/bin/env bash
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$ROOT"

TMUX_OUT=${CHROOTCTL_TMUX_OUTPUT:-$ROOT/out/tmux/arm64-v8a}
TREE=${CHROOTCTL_MODULE_TREE:-$ROOT/out/module}
ZIP=${CHROOTCTL_MODULE_ZIP:-$ROOT/out/chrootctl.zip}
SUM=${ZIP}.sha256

record() {
  scripts/devtool/root-module-evidence.sh record "$1" "$2"
}

case "${1:-}" in
  restore-reset)
    scripts/devtool/root-module-evidence.sh reset
    ;;
  restore-go)
    command -v go >/dev/null 2>&1 || { echo "go is required" >&2; exit 127; }
    go mod download
    go mod verify
    ;;
  restore-tmux)
    CHROOTCTL_TMUX_FETCH_ONLY=1 scripts/tmux/build-static-android-arm64.sh
    ;;
  restore-seal)
    command -v node >/dev/null 2>&1 || { echo "node is required for WebUI validation" >&2; exit 127; }
    record root_restore 'devtool root-module restore DAG'
    ;;

  build-tmux)
    if [[ ${CHROOTCTL_SKIP_TMUX_BUILD:-0} != 1 ]]; then
      scripts/tmux/build-static-android-arm64.sh
    fi
    ;;
  build-tmux-verify)
    scripts/tmux/verify-static-android-arm64.sh "$TMUX_OUT/tmux" "$TMUX_OUT/tmux-runtime-manifest.json"
    ;;
  build-repoctl)
    mkdir -p out
    go build -v -o out/repoctl-devtool ./cmd/repoctl
    ;;
  build-runtime)
    CHROOTCTL_TMUX_PATH="$TMUX_OUT/tmux" CHROOTCTL_REQUIRE_TMUX=1 \
      out/repoctl-devtool build-runtime \
      --output-root out/native-runtime \
      --jobs "${DEVTOOL_MAX_WORKERS:-2}"
    ;;
  build-module)
    out/repoctl-devtool build-module \
      --runtime-dir out/native-runtime/arm64-v8a \
      --output-dir out/module \
      --zip out/chrootctl.zip \
      --jobs "${DEVTOOL_MAX_WORKERS:-2}" \
      --checksum
    ;;
  build-seal)
    test -s out/chrootctl.zip
    test -s out/chrootctl.zip.sha256
    test -d out/module
    record root_build 'devtool root-module build DAG'
    ;;

  test-webui)
    command -v node >/dev/null 2>&1 || { echo "node is required for WebUI validation" >&2; exit 127; }
    node --check internal/module/webroot/kernelsu.js
    node --check internal/module/webroot/chrootctl.js
    node --check internal/module/webroot/index.js
    for test_file in \
      internal/module/webui_transport_test.mjs \
      internal/module/webui_bridge_ui_test.mjs \
      internal/module/webui_post_cux_transport_test.mjs \
      internal/module/webui_install_failure_transport_test.mjs
    do
      [[ ! -f "$test_file" ]] || node "$test_file"
    done
    ;;
  test-go)
    go test \
      ./internal/module \
      ./internal/standalonewebui \
      ./internal/install/... \
      ./internal/integrity \
      ./internal/bridge \
      ./internal/operations \
      ./internal/users \
      ./internal/services \
      ./internal/rcloneops \
      ./internal/catalog \
      ./internal/repoctl \
      ./internal/config \
      ./internal/logging \
      ./internal/clipboard \
      ./internal/skybindr1
    ;;
  test-tmux)
    go test ./internal/repoctl -run 'TestTMUX01'
    bash scripts/tmux/test-android-glob-compat.sh
    bash scripts/tmux/test-android-langinfo-compat.sh
    bash scripts/tmux/test-build-fingerprint.sh
    ;;
  test-seal)
    record root_test 'devtool root-module test DAG'
    ;;

  lint-go)
    changed_go="$({
      git diff --name-only --diff-filter=ACMR HEAD -- '*.go' 2>/dev/null || true
      git ls-files --others --exclude-standard -- '*.go' 2>/dev/null || true
    } | sort -u)"
    if [[ -n "$changed_go" ]]; then
      unformatted="$(printf '%s\n' "$changed_go" | while IFS= read -r file; do [[ ! -f "$file" ]] || gofmt -l "$file"; done)"
      if [[ -n "$unformatted" ]]; then
        echo "gofmt required for changed Go files:" >&2
        printf '%s\n' "$unformatted" >&2
        exit 1
      fi
    else
      echo "No changed Go files require gofmt checking."
    fi
    go vet \
      ./cmd/chrootctl ./cmd/repoctl ./internal/module ./internal/standalonewebui \
      ./internal/install/... ./internal/integrity ./internal/bridge ./internal/operations \
      ./internal/users ./internal/services ./internal/rcloneops ./internal/catalog \
      ./internal/repoctl ./internal/config ./internal/logging ./internal/clipboard
    ;;
  lint-native)
    bash -n \
      scripts/tmux/build-static-android-arm64.sh \
      scripts/tmux/verify-static-android-arm64.sh \
      scripts/tmux/check-reproducible.sh \
      scripts/tmux/test-android-glob-compat.sh \
      scripts/tmux/test-android-langinfo-compat.sh
    clang -Wall -Wextra -Werror -DCHROOTCTL_ANDROID_GLOB_COMPAT=1 -Iscripts/tmux -fsyntax-only scripts/tmux/android-glob-compat.c
    clang -Wall -Wextra -Werror -DCHROOTCTL_ANDROID_LANGINFO_COMPAT=1 -Iscripts/tmux -fsyntax-only scripts/tmux/android-langinfo-compat.c
    sh -n \
      scripts/devtool/root-module-build.sh \
      scripts/devtool/root-module-restore.sh \
      scripts/devtool/root-module-test.sh \
      scripts/devtool/root-module-package.sh \
      scripts/devtool/root-module-lint.sh \
      scripts/devtool/root-module-evidence.sh
    bash -n scripts/devtool/root-module-stage.sh
    ;;
  lint-seal)
    record root_lint 'devtool root-module lint DAG'
    ;;

  package-preflight)
    test -s "$ZIP" || { echo "missing module ZIP: $ZIP" >&2; exit 1; }
    test -s "$SUM" || { echo "missing module checksum: $SUM" >&2; exit 1; }
    test -d "$TREE" || { echo "missing expanded module tree: $TREE" >&2; exit 1; }
    expected=$(awk 'NR==1 {print $1}' "$SUM")
    actual=$(sha256sum "$ZIP" | awk '{print $1}')
    [[ -n "$expected" && "$expected" == "$actual" ]] || { echo "module checksum mismatch" >&2; exit 1; }
    for required in \
      module.prop post-fs-data.sh service.sh action.sh \
      config/chrootctl/runtime-executables.list system/bin/chrootctl \
      webroot/index.html webroot/index.js webroot/chrootctl.js webroot/kernelsu.js \
      runtime/arm64-v8a/chrootctl runtime/arm64-v8a/runtime-manifest.json \
      runtime/arm64-v8a/tmux runtime/arm64-v8a/tmux-runtime-manifest.json runtime/arm64-v8a/tmux.sha256
    do
      [[ -e "$TREE/$required" ]] || { echo "module package missing required path: $required" >&2; exit 1; }
    done
    grep -Fq '[targets.chrootctl_root_module]' .devtool.toml || { echo "chrootctl_root_module Devtool target missing" >&2; exit 1; }
    ! grep -Fq '[targets.chrootctl_android]' .devtool.toml || { echo "retired standalone Android target unexpectedly returned" >&2; exit 1; }
    [[ -x "$TREE/system/bin/chrootctl" ]] || { echo "packaged chrootctl backend is not executable" >&2; exit 1; }
    while IFS= read -r runtime_rel || [[ -n "$runtime_rel" ]]; do
      [[ -n "$runtime_rel" ]] || continue
      case "$runtime_rel" in /*|..|../*|*/../*|*/..) echo "unsafe runtime executable inventory path: $runtime_rel" >&2; exit 1;; esac
      runtime_path="$TREE/runtime/arm64-v8a/$runtime_rel"
      [[ -f "$runtime_path" && ! -L "$runtime_path" && -x "$runtime_path" ]] || { echo "runtime executable inventory points at missing/non-executable file: $runtime_rel" >&2; exit 1; }
      mode=$(stat -c '%a' "$runtime_path")
      [[ "$mode" == 755 ]] || { echo "runtime executable mode is $mode, want 755: $runtime_rel" >&2; exit 1; }
    done < "$TREE/config/chrootctl/runtime-executables.list"
    grep -Fq 'restore_runtime_exec_modes "$RUNTIME_ROOT" "$RUNTIME_EXEC_LIST"' "$TREE/customize.sh" || { echo "installer does not restore sealed runtime executable inventory" >&2; exit 1; }
    grep -Fq 'runtime_execs_ready "$LIVE_NEXT/runtime/arm64-v8a" "$LIVE_NEXT/config/chrootctl/runtime-executables.list"' "$TREE/customize.sh" || { echo "live-update preflight does not verify every sealed runtime executable" >&2; exit 1; }
    ;;
  package-runtime)
    scripts/tmux/verify-static-android-arm64.sh "$TREE/runtime/arm64-v8a/tmux" "$TREE/runtime/arm64-v8a/tmux-runtime-manifest.json"
    tmux_tree_sha=$(sha256sum "$TREE/runtime/arm64-v8a/tmux" | awk '{print $1}')
    tmux_sidecar_sha=$(awk 'NR==1 {print $1}' "$TREE/runtime/arm64-v8a/tmux.sha256")
    [[ "$tmux_tree_sha" == "$tmux_sidecar_sha" ]] || { echo "packaged tmux checksum sidecar mismatch" >&2; exit 1; }
    command -v unzip >/dev/null 2>&1 || { echo "unzip is required for package seal" >&2; exit 127; }
    tmux_zip_sha=$(unzip -p "$ZIP" runtime/arm64-v8a/tmux | sha256sum | awk '{print $1}')
    [[ "$tmux_zip_sha" == "$tmux_tree_sha" ]] || { echo "module ZIP tmux bytes differ from sealed runtime" >&2; exit 1; }
    runtime_manifest="$TREE/runtime/arm64-v8a/runtime-manifest.json"
    if grep -Eq '"[Pp]ath"[[:space:]]*:[[:space:]]*"rclone"' "$runtime_manifest"; then
      rclone="$TREE/runtime/arm64-v8a/rclone"
      [[ -f "$rclone" && -x "$rclone" && ! -L "$rclone" ]] || { echo "runtime manifest inventories rclone but packaged executable is missing/unsafe" >&2; exit 1; }
      rclone_tree_sha=$(sha256sum "$rclone" | awk '{print $1}')
      rclone_zip_sha=$(unzip -p "$ZIP" runtime/arm64-v8a/rclone | sha256sum | awk '{print $1}')
      [[ "$rclone_tree_sha" == "$rclone_zip_sha" ]] || { echo "module ZIP rclone bytes differ from sealed runtime" >&2; exit 1; }
    fi
    ;;
  package-webui)
    grep -Fq '127.0.0.1:0' internal/standalonewebui/server.go || { echo "standalone WebUI is not loopback-only" >&2; exit 1; }
    if grep -REn 'mux\.Handle(Func)?\("/api/v1/(shell|exec|argv|root-rpc|rpc|command)(/|"|\?)' internal/standalonewebui/*.go >/dev/null 2>&1; then
      echo "unsafe generic privileged HTTP route registered" >&2
      exit 1
    fi
    grep -Fq 'action.sh' internal/module/module.go || { echo "standalone Action launcher missing" >&2; exit 1; }
    grep -Fq 'case <-srv.Done()' cmd/chrootctl/main.go || { echo "standalone server process does not exit after idle shutdown" >&2; exit 1; }
    ;;
  package-evidence)
    scripts/devtool/root-module-evidence.sh require root_restore root_build root_test root_lint
    out/repoctl-devtool seal-root-module-evidence --markers out/devtool-evidence --module-dir "$TREE" --zip "$ZIP" --checksum=true
    expected=$(awk 'NR==1 {print $1}' "$SUM")
    actual=$(sha256sum "$ZIP" | awk '{print $1}')
    [[ -n "$expected" && "$expected" == "$actual" ]] || { echo "post-evidence module checksum mismatch" >&2; exit 1; }
    [[ -s "$TREE/config/chrootctl/validation-results.json" ]] || { echo "root-module validation evidence was not embedded" >&2; exit 1; }
    mode=$(stat -c '%a' "$TREE/config/chrootctl/validation-results.json")
    [[ "$mode" == 600 ]] || { echo "root-module validation evidence mode is $mode, want 600" >&2; exit 1; }
    ;;
  *)
    echo "usage: root-module-stage.sh <restore-reset|restore-go|restore-tmux|restore-seal|build-tmux|build-tmux-verify|build-repoctl|build-runtime|build-module|build-seal|test-webui|test-go|test-tmux|test-seal|lint-go|lint-native|lint-seal|package-preflight|package-runtime|package-webui|package-evidence>" >&2
    exit 2
    ;;
esac
