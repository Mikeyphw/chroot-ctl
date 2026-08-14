#!/bin/sh
set -eu

case "${CHROOTCTL_DISTRO:?}" in
  ubuntu)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y gnome-shell gnome-session gnome-terminal nautilus file-roller gdm3 dbus-x11
    ;;
  arch)
    pacman -Syu --noconfirm --needed gnome gnome-tweaks gdm
    ;;
  *)
    echo "unsupported distro: ${CHROOTCTL_DISTRO}" >&2
    exit 1
    ;;
esac
