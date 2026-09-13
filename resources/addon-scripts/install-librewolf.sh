#!/bin/sh
set -eu

case "${CHROOTCTL_DISTRO:?}" in
  ubuntu)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y flatpak xdg-desktop-portal xdg-desktop-portal-gtk ca-certificates
    ;;
  arch)
    pacman -Sy --noconfirm --needed flatpak xdg-desktop-portal xdg-desktop-portal-gtk
    ;;
  *)
    echo "unsupported distro: ${CHROOTCTL_DISTRO}" >&2
    exit 1
    ;;
esac

flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
flatpak install -y --noninteractive flathub io.gitlab.librewolf-community

echo "LibreWolf installed from Flathub."
