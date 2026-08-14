#!/bin/sh
set -eu

case "${CHROOTCTL_DISTRO:?}" in
  ubuntu)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y gimp
    ;;
  arch)
    pacman -Syu --noconfirm --needed gimp
    ;;
  *)
    echo "unsupported distro: ${CHROOTCTL_DISTRO}" >&2
    exit 1
    ;;
esac
