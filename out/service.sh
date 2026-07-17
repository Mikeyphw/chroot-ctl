#!/system/bin/sh
MODDIR=${0%/*}
HELPER="$MODDIR/bin/chrootctl-magisk-helper"
STATE_FILE="$MODDIR/config/chrootctl/boot_targets.json"
WEBUI_SERVICE="$MODDIR/bin/chrootctl-webui-service"
export PATH="$MODDIR/system/bin:/system/bin:/system/xbin:/data/adb/magisk:$PATH"
[ -f "$MODDIR/config/chrootctl/python.env" ] && . "$MODDIR/config/chrootctl/python.env"

[ -x "$HELPER" ] && [ -f "$STATE_FILE" ] && "$HELPER" boot "$STATE_FILE" "$MODDIR" >/dev/null 2>&1 || true
"$MODDIR/system/bin/chrootctl" clipboard daemon start >/dev/null 2>&1 || true

[ -x "$WEBUI_SERVICE" ] && "$WEBUI_SERVICE" start "$MODDIR" >/dev/null 2>&1 || true
[ -x "$WEBUI_SERVICE" ] && "$WEBUI_SERVICE" watch "$MODDIR" >/dev/null 2>&1 &

exit 0
