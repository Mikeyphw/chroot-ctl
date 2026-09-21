#!/system/bin/sh
set -eu
MOD="${CHROOTCTL_MODULE_DIR:-/data/adb/modules/chrootctl-magisk}"
ACTION="$MOD/action.sh"
LOG="/data/local/tmp/chrootctl/standalone-webui.log"
PIDFILE="/data/local/tmp/chrootctl/standalone-webui.pid"
[ -x "$ACTION" ] || { echo "FAIL action missing: $ACTION"; exit 1; }
rm -f "$LOG" "$PIDFILE" 2>/dev/null || true
CHROOTCTL_MODULE_DIR="$MOD" "$ACTION" >/data/local/tmp/chrootctl/action-smoke.out 2>&1
for _ in 1 2 3 4 5 6 7 8 9 10; do
  [ -s "$PIDFILE" ] && grep -q 'http://127.0.0.1:' "$LOG" 2>/dev/null && break
  sleep 1
done
PID="$(cat "$PIDFILE" 2>/dev/null || true)"
case "$PID" in ''|*[!0-9]*) echo "FAIL no valid server pid"; cat "$LOG" 2>/dev/null || true; exit 1;; esac
kill -0 "$PID" 2>/dev/null || { echo "FAIL server died after Action returned"; cat "$LOG" 2>/dev/null || true; exit 1; }
BOOT="$(sed -n 's#.*\(http://127\.0\.0\.1:[0-9][0-9]*/bootstrap?token=[A-Za-z0-9_-]*\).*#\1#p' "$LOG" | tail -1)"
[ -n "$BOOT" ] || { echo "FAIL bootstrap URL missing"; cat "$LOG"; exit 1; }
HOST="${BOOT%%/bootstrap*}"
command -v curl >/dev/null 2>&1 || { echo "PASS lifecycle: pid=$PID (curl unavailable, HTTP probe skipped)"; exit 0; }
COOKIE="/data/local/tmp/chrootctl/lifecycle-smoke.cookies.$$"
trap 'rm -f "$COOKIE"' EXIT INT TERM
curl -fsS -c "$COOKIE" -b "$COOKIE" "$BOOT" >/dev/null
sleep 1
kill -0 "$PID" 2>/dev/null || { echo "FAIL server died after bootstrap"; cat "$LOG"; exit 1; }
curl -fsS -c "$COOKIE" -b "$COOKIE" "$HOST/api/v1/health" | grep -q standalone-loopback || { echo "FAIL health after Action return"; cat "$LOG"; exit 1; }
echo "STANDALONE WEBUI LIFECYCLE SMOKE PASS pid=$PID host=$HOST"
