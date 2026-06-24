#!/bin/sh
set -eu

case "${CHROOTCTL_DISTRO:?}" in
  ubuntu)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y git curl wget ca-certificates build-essential pkg-config openssh-client
    ;;
  arch)
    pacman -Sy --noconfirm --needed git curl wget ca-certificates base-devel pkgconf openssh
    ;;
  *)
    echo "unsupported distro: ${CHROOTCTL_DISTRO}" >&2
    exit 1
    ;;
esac

echo "Development basics installed."
