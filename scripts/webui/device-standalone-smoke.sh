#!/system/bin/sh
set -eu
BIN="${CHROOTCTL_BIN:-/data/adb/modules/chrootctl/system/bin/chrootctl}"
MOD="${CHROOTCTL_MODULE_DIR:-/data/adb/modules/chrootctl}"
TMP="/data/local/tmp/chrootctl-swui-smoke.$$"
LOG="$TMP/server.log"
COOKIE="$TMP/cookies"
mkdir -p "$TMP"; chmod 0700 "$TMP"
cleanup(){ [ -n "${PID:-}" ] && kill "$PID" 2>/dev/null || true; rm -rf "$TMP"; }
trap cleanup EXIT INT TERM
[ -x "$BIN" ] || { echo "FAIL backend missing: $BIN"; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "SKIP curl is required for HTTP device smoke"; exit 2; }
CHROOTCTL_MODULE_DIR="$MOD" "$BIN" webui serve --json >"$LOG" 2>&1 & PID=$!
for _ in 1 2 3 4 5 6 7 8 9 10; do grep -q 'bootstrapUrl' "$LOG" && break; sleep 1; done
BOOT="$(sed -n 's/.*"bootstrapUrl":"\([^"]*\)".*/\1/p' "$LOG" | head -1)"
[ -n "$BOOT" ] || { echo "FAIL no bootstrap URL"; cat "$LOG"; exit 1; }
HOST="${BOOT%%/bootstrap*}"
case "$HOST" in http://127.0.0.1:*) ;; *) echo "FAIL non-loopback URL: $HOST"; exit 1;; esac
code="$(curl -sS -o /dev/null -w '%{http_code}' "$HOST/api/v1/health")"; [ "$code" = 401 ] || { echo "FAIL unauthenticated health=$code"; exit 1; }
curl -sS -L -c "$COOKIE" -b "$COOKIE" "$BOOT" -o "$TMP/index.html"
grep -q '<html\|<!doctype' "$TMP/index.html" || { echo "FAIL bootstrap did not reach WebUI"; exit 1; }
code="$(curl -sS -o "$TMP/replay" -w '%{http_code}' -c "$COOKIE" -b "$COOKIE" "$BOOT")"; [ "$code" = 401 ] || { echo "FAIL bootstrap replay=$code"; exit 1; }
curl -sS -c "$COOKIE" -b "$COOKIE" "$HOST/api/v1/health" | grep -q 'standalone-loopback' || { echo "FAIL authenticated health"; exit 1; }
curl -sS -c "$COOKIE" -b "$COOKIE" "$HOST/api/v1/capabilities" | grep -q 'protocolVersion' || { echo "FAIL capabilities"; exit 1; }
# A mutation without Origin/CSRF must be rejected before dispatch.
code="$(curl -sS -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' --data '{}' -c "$COOKIE" -b "$COOKIE" "$HOST/api/v1/run/sessions.reconcile")"; [ "$code" = 403 ] || { echo "FAIL mutation boundary=$code"; exit 1; }
echo "SWUI-04 DEVICE SMOKE PASS"
echo "Manual: verify Action opens browser; reopen tab; tmux input/capture/resize/reconnect; multiple chroots/users; reboot then launch again."
