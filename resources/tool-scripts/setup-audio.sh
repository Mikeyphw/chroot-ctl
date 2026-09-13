#!/bin/sh
set -eu

case "${CHROOTCTL_DISTRO:?}" in
  ubuntu)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y pipewire pipewire-pulse wireplumber pavucontrol alsa-utils pulseaudio-utils dbus-user-session
    ;;
  arch)
    pacman -Sy --noconfirm --needed pipewire pipewire-pulse wireplumber pavucontrol alsa-utils pipewire-alsa pipewire-jack
    ;;
  *)
    echo "unsupported distro: ${CHROOTCTL_DISTRO}" >&2
    exit 1
    ;;
esac

echo "Audio packages installed. Start PipeWire/WirePlumber in the session manager used by your desktop."
