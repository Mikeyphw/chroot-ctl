#!/bin/sh
set -eu

case "${CHROOTCTL_DISTRO:?}" in
  ubuntu)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y file-roller
    ;;
  arch)
    pacman -Syu --noconfirm --needed file-roller
    ;;
  *)
    echo "unsupported distro: ${CHROOTCTL_DISTRO}" >&2
    exit 1
    ;;
esac
