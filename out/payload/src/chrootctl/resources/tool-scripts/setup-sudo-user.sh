#!/bin/sh
set -eu

user_name="${CHROOTCTL_USERNAME:-user}"

case "${CHROOTCTL_DISTRO:?}" in
  ubuntu)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y sudo
    group_name="sudo"
    ;;
  arch)
    pacman -Sy --noconfirm --needed sudo
    group_name="wheel"
    ;;
  *)
    echo "unsupported distro: ${CHROOTCTL_DISTRO}" >&2
    exit 1
    ;;
esac

if ! getent group "$group_name" >/dev/null 2>&1; then
  groupadd "$group_name"
fi

if ! id "$user_name" >/dev/null 2>&1; then
  useradd -m -s /bin/bash "$user_name"
fi

usermod -aG "$group_name" "$user_name"
mkdir -p /etc/sudoers.d
case "$group_name" in
  sudo)
    printf '%%%s ALL=(ALL:ALL) ALL\n' "$group_name" >/etc/sudoers.d/90-chrootctl-user
    ;;
  wheel)
    printf '%%%s ALL=(ALL:ALL) ALL\n' "$group_name" >/etc/sudoers.d/90-chrootctl-user
    ;;
esac
chmod 440 /etc/sudoers.d/90-chrootctl-user

echo "User ${user_name} is ready for sudo through group ${group_name}."
