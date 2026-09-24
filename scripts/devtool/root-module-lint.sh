#!/usr/bin/env sh
set -eu

echo "== chrootctl root module: lint =="

# Do not make historical formatting debt a new validation failure.
# Enforce gofmt on Go files changed in the current worktree, including untracked
# files, while vetting the complete root-module package surface.
changed_go="$(
  {
    git diff --name-only --diff-filter=ACMR HEAD -- '*.go'
    git ls-files --others --exclude-standard -- '*.go'
  } | sort -u
)"

if [ -n "$changed_go" ]; then
  unformatted="$(
    printf '%s\n' "$changed_go" |
      while IFS= read -r file; do
        [ -f "$file" ] || continue
        gofmt -l "$file"
      done
  )"
  if [ -n "$unformatted" ]; then
    echo "gofmt required for changed Go files:" >&2
    printf '%s\n' "$unformatted" >&2
    exit 1
  fi
else
  echo "No changed Go files require gofmt checking."
fi

go vet \
  ./cmd/chrootctl \
  ./cmd/repoctl \
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
  ./internal/clipboard

# TMUX-01 shell/runtime contract lint.
bash -n scripts/tmux/build-static-android-arm64.sh scripts/tmux/verify-static-android-arm64.sh scripts/tmux/check-reproducible.sh scripts/tmux/test-android-glob-compat.sh
clang -Wall -Wextra -Werror -DCHROOTCTL_ANDROID_GLOB_COMPAT=1 -Iscripts/tmux -fsyntax-only scripts/tmux/android-glob-compat.c
sh -n scripts/devtool/root-module-build.sh scripts/devtool/root-module-restore.sh scripts/devtool/root-module-test.sh scripts/devtool/root-module-package.sh scripts/devtool/root-module-evidence.sh
scripts/devtool/root-module-evidence.sh record root_lint 'scripts/devtool/root-module-lint.sh'
