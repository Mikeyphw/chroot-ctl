#!/bin/sh
set -eu

case "${CHROOTCTL_DISTRO:?}" in
  ubuntu)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y cinnamon nemo nemo-fileroller lightdm slick-greeter
    ;;
  arch)
    pacman -Syu --noconfirm --needed cinnamon nemo-fileroller lightdm lightdm-slick-greeter
    ;;
  *)
    echo "unsupported distro: ${CHROOTCTL_DISTRO}" >&2
    exit 1
    ;;
esac
