#!/usr/bin/env sh
set -eu
ZIP="${1:-out/chrootctl.zip}"
[ -s "$ZIP" ] || { echo "module ZIP not found: $ZIP; run the build/package phase first" >&2; exit 2; }
case "$ZIP" in /*) ABS="$ZIP";; *) ABS="$PWD/$ZIP";; esac

echo "== chrootctl root module: KernelSU install =="
command -v su >/dev/null 2>&1 || { echo "su is unavailable" >&2; exit 127; }

KSUD="$(su -c 'command -v ksud 2>/dev/null' | tr -d '\r' | head -n 1)"
case "$KSUD" in
  /*) ;;
  "") echo "KernelSU installer unavailable: su -c 'command -v ksud' returned no path" >&2; exit 127 ;;
  *) echo "Unsafe ksud path returned by root shell: $KSUD" >&2; exit 126 ;;
esac

su -c "[ -f '$KSUD' ] && [ -x '$KSUD' ]" || {
  echo "ksud path is not an executable regular file: $KSUD" >&2
  exit 126
}

echo "Using KernelSU: $KSUD"
# Pass the exact discovered executable path; do not rely on root-shell PATH again.
exec su -c "'$KSUD' module install '$ABS'"
