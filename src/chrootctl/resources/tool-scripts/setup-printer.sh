#!/bin/sh
set -eu

case "${CHROOTCTL_DISTRO:?}" in
  ubuntu)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y cups cups-client cups-bsd printer-driver-gutenprint avahi-daemon
    ;;
  arch)
    pacman -Syu --noconfirm --needed cups gutenprint avahi nss-mdns system-config-printer
    ;;
  *)
    echo "unsupported distro: ${CHROOTCTL_DISTRO}" >&2
    exit 1
    ;;
esac

echo "Printing packages installed. Enable cups/avahi on the host side or inside a managed init environment if needed."
