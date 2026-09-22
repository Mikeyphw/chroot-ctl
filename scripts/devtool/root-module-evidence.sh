#!/usr/bin/env sh
set -eu
DIR="${CHROOTCTL_DEVTOOL_EVIDENCE_DIR:-out/devtool-evidence}"
cmd="${1:-}"
case "$cmd" in
  reset)
    rm -rf "$DIR"
    mkdir -p "$DIR"
    ;;
  record)
    stage="${2:-}"
    shift 2 || true
    [ -n "$stage" ] || { echo "evidence stage is required" >&2; exit 2; }
    mkdir -p "$DIR"
    command_text="$*"
    [ -n "$command_text" ] || { echo "evidence command is required" >&2; exit 2; }
    tmp="$DIR/$stage.ok.tmp.$$"
    {
      date +%s
      printf '%s\n' "$command_text"
    } > "$tmp"
    chmod 0600 "$tmp" 2>/dev/null || true
    mv -f "$tmp" "$DIR/$stage.ok"
    ;;
  require)
    shift || true
    for stage in "$@"; do
      [ -s "$DIR/$stage.ok" ] || { echo "missing successful Devtool stage marker: $stage" >&2; exit 1; }
    done
    ;;
  *)
    echo "usage: root-module-evidence.sh <reset|record|require> ..." >&2
    exit 2
    ;;
esac
