#!/bin/sh
set -eu

case "${CHROOTCTL_DISTRO:?}" in
  ubuntu)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y xfce4 xfce4-goodies dbus-x11 xterm
    ;;
  arch)
    pacman -Syu --noconfirm --needed xfce4 xfce4-goodies xterm
    ;;
  *)
    echo "unsupported distro: ${CHROOTCTL_DISTRO}" >&2
    exit 1
    ;;
esac
