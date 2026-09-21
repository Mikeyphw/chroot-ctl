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
