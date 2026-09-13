#!/bin/sh
set -eu

case "${CHROOTCTL_DISTRO:?}" in
  ubuntu)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    dpkg --add-architecture i386
    apt-get update
    if ! apt-cache show wine-staging >/dev/null 2>&1; then
      echo "wine-staging is not available in the current Ubuntu sources; no alternate Wine package was installed." >&2
      exit 65
    fi
    apt-get install -y wine-staging winbind cabextract
    ;;
  arch)
    pacman -Sy --noconfirm --needed wine-staging winetricks
    ;;
  *)
    echo "unsupported distro: ${CHROOTCTL_DISTRO}" >&2
    exit 1
    ;;
esac
