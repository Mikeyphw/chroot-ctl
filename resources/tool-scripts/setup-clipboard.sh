#!/bin/sh
set -eu

case "${CHROOTCTL_DISTRO:?}" in
  ubuntu)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y xclip xsel wl-clipboard jq socat
    ;;
  arch)
    pacman -Sy --noconfirm --needed xclip xsel wl-clipboard jq socat
    ;;
  *)
    echo "unsupported distro: ${CHROOTCTL_DISTRO}" >&2
    exit 1
    ;;
esac

install -d /usr/local/bin

target_name="${CHROOTCTL_NAME:?}"
target_escaped=$(printf '%s' "$target_name" | sed "s/'/'\\''/g")

cat >/usr/local/bin/termux-clip <<'EOF_INNER'
#!/bin/sh
# chrootctl-clipboard-wrapper:v1 termux-clip
set -eu

SOCKET_PATH=/tmp/chrootctl/clipboard.sock
TOKEN_PATH=/tmp/chrootctl/clipboard.token
TARGET_NAME='__CHROOTCTL_NAME__'
MAX_CLIPBOARD_BYTES=1048576

[ -S "$SOCKET_PATH" ] || { echo "clipboard socket is unavailable: $SOCKET_PATH" >&2; exit 1; }
[ -r "$TOKEN_PATH" ] || { echo "clipboard token is unavailable: $TOKEN_PATH" >&2; exit 1; }
token=$(cat "$TOKEN_PATH")

mode=set
if [ "${1:-}" = "-o" ] || [ "${1:-}" = "--output" ]; then
  mode=get
  shift
elif [ "${1:-}" = "-i" ] || [ "${1:-}" = "--input" ]; then
  shift
fi

if [ "$mode" = get ]; then
  request=$(jq -cn --arg token "$token" --arg target "$TARGET_NAME" '{action:"get",token:$token,target:$target}')
else
  if [ "$#" -gt 0 ]; then
    byte_count=$(printf '%s' "$*" | wc -c | tr -d ' ')
    [ "$byte_count" -le "$MAX_CLIPBOARD_BYTES" ] || { echo "clipboard text exceeds 1 MiB" >&2; exit 1; }
    request=$(printf '%s' "$*" | jq -Rs --arg token "$token" --arg target "$TARGET_NAME" '{action:"set",token:$token,target:$target,text:.}')
  else
    tmp=$(mktemp)
    trap 'rm -f "$tmp"' EXIT HUP INT TERM
    cat >"$tmp"
    byte_count=$(wc -c <"$tmp" | tr -d ' ')
    [ "$byte_count" -le "$MAX_CLIPBOARD_BYTES" ] || { echo "clipboard text exceeds 1 MiB" >&2; exit 1; }
    request=$(jq -Rs --arg token "$token" --arg target "$TARGET_NAME" '{action:"set",token:$token,target:$target,text:.}' <"$tmp")
  fi
fi

response=$(printf '%s' "$request" | socat - "UNIX-CONNECT:$SOCKET_PATH")
ok=$(printf '%s' "$response" | jq -r '.ok // false')
if [ "$ok" != true ]; then
  printf '%s\n' "$(printf '%s' "$response" | jq -r '.error // "clipboard request failed"')" >&2
  exit 1
fi
if [ "$mode" = get ]; then
  printf '%s' "$response" | jq -rj '.text // ""'
fi
EOF_INNER
sed -i "s|__CHROOTCTL_NAME__|$target_escaped|g" /usr/local/bin/termux-clip

cat >/usr/local/bin/chrootctl-xsel <<'EOF_INNER'
#!/bin/sh
# chrootctl-clipboard-wrapper:v1 chrootctl-xsel
set -eu

mode="set"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --clipboard|-b|--primary|-p|--secondary|-s)
      shift
      ;;
    --input|-i)
      mode="set"; shift
      ;;
    --output|-o)
      mode="get"; shift
      ;;
    --clear|-c)
      printf '' | exec /usr/local/bin/termux-clip
      ;;
    --)
      shift; break
      ;;
    -*)
      echo "chrootctl-xsel: unsupported option: $1" >&2
      exit 2
      ;;
    *)
      break
      ;;
  esac
done

if [ "$mode" = "get" ]; then
  exec /usr/local/bin/termux-clip --output
fi

exec /usr/local/bin/termux-clip "$@"
EOF_INNER

cat >/usr/local/bin/chrootctl-xclip <<'EOF_INNER'
#!/bin/sh
# chrootctl-clipboard-wrapper:v1 chrootctl-xclip
set -eu

mode="set"
while [ "$#" -gt 0 ]; do
  case "$1" in
    -selection|--selection|-display|--display|-loops|--loops|-target|--target)
      [ "$#" -ge 2 ] || { echo "chrootctl-xclip: $1 requires a value" >&2; exit 2; }
      shift 2
      ;;
    -i|-in|--input)
      mode="set"; shift
      ;;
    -o|-out|--output)
      mode="get"; shift
      ;;
    -quiet|-silent|-verbose|-rmlastnl|-noutf8|-filter)
      shift
      ;;
    --)
      shift; break
      ;;
    -*)
      echo "chrootctl-xclip: unsupported option: $1" >&2
      exit 2
      ;;
    *)
      break
      ;;
  esac
done

if [ "$mode" = "get" ]; then
  exec /usr/local/bin/termux-clip --output
fi

exec /usr/local/bin/termux-clip "$@"
EOF_INNER

chmod 0755 /usr/local/bin/termux-clip /usr/local/bin/chrootctl-xsel /usr/local/bin/chrootctl-xclip

echo "Clipboard helpers installed. Use termux-clip, chrootctl-xsel, or chrootctl-xclip for the host bridge; system xsel/xclip are left untouched."
echo "Requires a running host daemon at /tmp/chrootctl/clipboard.sock."
