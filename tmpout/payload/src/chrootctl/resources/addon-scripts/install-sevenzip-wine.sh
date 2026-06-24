#!/bin/sh
set -eu

case "${CHROOTCTL_DISTRO:?}" in
  ubuntu)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    dpkg --add-architecture i386
    apt-get update
    apt-get install -y p7zip-full wine winbind cabextract
    ;;
  arch)
    pacman -Sy --noconfirm --needed 7zip wine winetricks
    ;;
  *)
    echo "unsupported distro: ${CHROOTCTL_DISTRO}" >&2
    exit 1
    ;;
esac
