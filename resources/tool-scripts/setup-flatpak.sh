#!/bin/sh
set -eu

install_flatpak_packages() {
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
}

install_flatpak_packages

if ! flatpak remote-list 2>/dev/null | awk 'NR > 0 {print $1}' | grep -qx flathub; then
  flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
fi

echo "Flatpak and Flathub are configured."
