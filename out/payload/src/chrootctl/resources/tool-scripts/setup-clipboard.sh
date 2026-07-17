#!/bin/sh
set -eu

case "${CHROOTCTL_DISTRO:?}" in
  ubuntu)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y xclip xsel wl-clipboard python3
    ;;
  arch)
    pacman -Sy --noconfirm --needed xclip xsel wl-clipboard python
    ;;
  *)
    echo "unsupported distro: ${CHROOTCTL_DISTRO}" >&2
    exit 1
    ;;
esac

install -d /usr/local/bin

cat >/usr/local/bin/termux-clip <<'EOF'
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
import sys

SOCKET_PATH = "/tmp/chrootctl/clipboard.sock"


def request(payload: dict[str, object]) -> dict[str, object]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(SOCKET_PATH)
        client.sendall(json.dumps(payload).encode("utf-8"))
        client.shutdown(socket.SHUT_WR)
        chunks: list[bytes] = []
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    response = json.loads(b"".join(chunks).decode("utf-8"))
    if not isinstance(response, dict):
        raise RuntimeError("clipboard daemon returned an invalid response")
    return response


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-o", "--output", action="store_true")
    parser.add_argument("-i", "--input", action="store_true")
    parser.add_argument("text", nargs="*")
    args = parser.parse_args()

    if args.output:
        payload = request({"action": "get"})
        if not payload.get("ok"):
            print(str(payload.get("error", "clipboard get failed")), file=sys.stderr)
            return 1
        sys.stdout.write(str(payload.get("text", "")))
        return 0

    text = " ".join(args.text) if args.text else sys.stdin.read()
    payload = request({"action": "set", "text": text})
    if not payload.get("ok"):
        print(str(payload.get("error", "clipboard set failed")), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
EOF

cat >/usr/local/bin/xsel <<'EOF'
#!/bin/sh
set -eu

mode="set"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --clipboard|-b|--primary|--secondary|-p)
      shift
      ;;
    --input|-i)
      mode="set"
      shift
      ;;
    --output|-o)
      mode="get"
      shift
      ;;
    --clear|-c)
      printf '' | exec /usr/local/bin/termux-clip
      ;;
    --)
      shift
      break
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
EOF

cat >/usr/local/bin/xclip <<'EOF'
#!/bin/sh
set -eu

mode="set"
while [ "$#" -gt 0 ]; do
  case "$1" in
    -selection|--selection)
      shift 2
      ;;
    clipboard|primary|secondary)
      shift
      ;;
    -i|--input)
      mode="set"
      shift
      ;;
    -o|--output)
      mode="get"
      shift
      ;;
    -quiet|-silent|-verbose|-loops|-display|-rmlastnl|-noutf8)
      shift
      [ "$#" -gt 0 ] && [ "${1#-}" != "$1" ] || true
      ;;
    --)
      shift
      break
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
EOF

chmod 0755 /usr/local/bin/termux-clip /usr/local/bin/xsel /usr/local/bin/xclip

echo "Clipboard helpers installed for X11/Wayland plus Termux host clipboard wrappers."
echo "Requires a running host daemon at /tmp/chrootctl/clipboard.sock."
