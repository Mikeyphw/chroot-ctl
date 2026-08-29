#!/bin/sh
set -eu

case "${CHROOTCTL_DISTRO:?}" in
  ubuntu)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y xclip xsel wl-clipboard python3
    ;;
  arch)
    pacman -Syu --noconfirm --needed xclip xsel wl-clipboard python
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
TOKEN_PATH = "/tmp/chrootctl/clipboard.token"
TIMEOUT_SECONDS = 5.0


def request(payload: dict[str, object]) -> dict[str, object]:
    payload = dict(payload)
    payload["token"] = open(TOKEN_PATH, "r", encoding="utf-8").read().strip()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(TIMEOUT_SECONDS)
        client.connect(SOCKET_PATH)
        client.sendall(json.dumps(payload).encode("utf-8"))
        client.shutdown(socket.SHUT_WR)
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > 1024 * 1024:
                raise RuntimeError("clipboard response exceeds 1 MiB")
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

cat >/usr/local/bin/chrootctl-xsel <<'EOF'
#!/bin/sh
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
EOF

cat >/usr/local/bin/chrootctl-xclip <<'EOF'
#!/bin/sh
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
EOF

chmod 0755 /usr/local/bin/termux-clip /usr/local/bin/chrootctl-xsel /usr/local/bin/chrootctl-xclip

echo "Clipboard helpers installed. Use termux-clip, chrootctl-xsel, or chrootctl-xclip for the host bridge; system xsel/xclip are left untouched."
echo "Requires a running host daemon at /tmp/chrootctl/clipboard.sock."
