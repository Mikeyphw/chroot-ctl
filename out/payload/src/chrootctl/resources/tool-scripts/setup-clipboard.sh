#!/bin/sh
set -eu

case "${CHROOTCTL_DISTRO:?}" in
  ubuntu)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y xclip xsel wl-clipboard
    ;;
  arch)
    pacman -Sy --noconfirm --needed xclip xsel wl-clipboard
    ;;
  *)
    echo "unsupported distro: ${CHROOTCTL_DISTRO}" >&2
    exit 1
    ;;
esac

echo "Clipboard helpers installed for X11 and Wayland sessions."
