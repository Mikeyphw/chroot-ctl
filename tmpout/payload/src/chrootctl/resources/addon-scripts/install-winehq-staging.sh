#!/bin/sh
set -eu

case "${CHROOTCTL_DISTRO:?}" in
  ubuntu)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    dpkg --add-architecture i386
    apt-get update
    if apt-cache show wine-staging >/dev/null 2>&1; then
      apt-get install -y wine-staging winbind cabextract
    else
      apt-get install -y wine winbind cabextract
      echo "wine-staging is not available in the current Ubuntu sources; installed wine instead." >&2
    fi
    ;;
  arch)
    pacman -Sy --noconfirm --needed wine-staging winetricks
    ;;
  *)
    echo "unsupported distro: ${CHROOTCTL_DISTRO}" >&2
    exit 1
    ;;
esac
