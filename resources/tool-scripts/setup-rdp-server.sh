#!/bin/sh
set -eu

case "${CHROOTCTL_DISTRO:?}" in
  ubuntu)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y xrdp xorgxrdp dbus-x11
    ;;
  arch)
    pacman -Syu --noconfirm --needed xrdp xorgxrdp
    ;;
  *)
    echo "unsupported distro: ${CHROOTCTL_DISTRO}" >&2
    exit 1
    ;;
esac

echo "XRDP installed. Pair this with a desktop addon and enable/start xrdp in the service manager that owns the chroot."
