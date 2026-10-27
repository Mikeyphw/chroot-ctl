#!/system/bin/sh
# Explicit, root-only persistent Chrootctl provider selector.
# It never touches Skybind's config, remotes, daemon, grants or mounts.
set -eu
umask 077

[ "$(id -u)" = 0 ] || { echo BLOCKED_CC_RCLONE_PROVIDER_ROOT_REQUIRED >&2; exit 2; }
case "${1:-}" in
  --check)
    [ "$#" = 1 ] || exit 2
    ;;
  --use)
    [ "$#" = 2 ] || exit 2
    case "$2" in skybind|chrootctl) : ;; *) echo BLOCKED_CC_RCLONE_UNKNOWN_PROVIDER >&2; exit 2 ;; esac
    ;;
  *) echo 'usage: sh select-skybind-rclone-provider.sh --check | --use skybind|chrootctl' >&2; exit 2 ;;
esac

state=/data/adb/chrootctl/rclone
provider="$state/provider"
parent=/data/adb/chrootctl
if [ -L "$state" ] || [ -L "$provider" ]; then
  echo BLOCKED_CC_RCLONE_PROVIDER_SYMLINK >&2; exit 2
fi
if [ -e "$state" ]; then
  [ -d "$state" ] || { echo BLOCKED_CC_RCLONE_INVALID_STATE_DIR >&2; exit 2; }
  [ "$(stat -c %u "$state")" = 0 ] || exit 2
  mode=$(stat -c %a "$state")
  # Policy is never broadened by chmod; reject group/other-writable dirs.
  case "$mode" in 700|750|755|710|711|500|550|555|510|511) : ;; *)
    # The Go backend separately checks exact ownership and writable bits.
    echo BLOCKED_CC_RCLONE_UNAPPROVED_DIRECTORY_MODE >&2; exit 2 ;;
  esac
fi
if [ -e "$provider" ]; then
  [ -f "$provider" ] && [ ! -L "$provider" ] || exit 2
  [ "$(stat -c %u "$provider")" = 0 ] || exit 2
  [ "$(stat -c %a "$provider")" = 600 ] || exit 2
  [ "$(stat -c %h "$provider")" = 1 ] || exit 2
  current=$(cat "$provider")
  case "$current" in skybind|chrootctl) : ;; *) echo BLOCKED_CC_RCLONE_INVALID_CURRENT_SELECTION >&2; exit 2 ;; esac
else
  current=chrootctl
fi

if [ "$1" = --check ]; then
  echo "PASS_CC_RCLONE_CURRENT_PROVIDER=$current"
  echo 'No module/config/remote mutated.'
  exit 0
fi

if [ "$current" = "$2" ] && [ -e "$provider" ]; then
  echo "PASS_CC_RCLONE_PROVIDER_ALREADY_SELECTED=$2"
  exit 0
fi
[ -d "$parent" ] && [ ! -L "$parent" ] && [ "$(stat -c %u "$parent")" = 0 ] || {
  echo BLOCKED_CC_RCLONE_STATE_ROOT_UNTRUSTED >&2; exit 2;
}
if [ ! -d "$state" ]; then
  mkdir -m 700 "$state"
  chown 0:0 "$state"
fi
# Each backup remains root-only and is retained for rollback.
if [ -e "$provider" ]; then
  backup=$(mktemp "$state/.provider-backup.XXXXXXXX")
  cp "$provider" "$backup"
  chown 0:0 "$backup"
  chmod 0600 "$backup"
  echo "provider_backup=$backup"
fi
new=$(mktemp "$state/.provider-new.XXXXXXXX")
trap 'rm -f "$new"' 0 HUP INT TERM
printf '%s\n' "$2" > "$new"
chown 0:0 "$new"
chmod 0600 "$new"
mv -f "$new" "$provider"
trap - 0 HUP INT TERM
[ "$(stat -c %u "$provider")" = 0 ] && [ "$(stat -c %a "$provider")" = 600 ] && [ "$(cat "$provider")" = "$2" ] || exit 2
echo "PASS_CC_RCLONE_PROVIDER_SELECTED=$2"
echo 'No Skybind config/grant/remote/mount touched; reopen long-lived Chrootctl processes.'
