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
    pacman -Syu --noconfirm --needed sudo
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

sudoers_dir=/etc/sudoers.d
sudoers_path="$sudoers_dir/90-chrootctl-user"
mkdir -p "$sudoers_dir"
[ ! -L "$sudoers_dir" ] || { echo "refusing symlink sudoers directory" >&2; exit 1; }
[ ! -L "$sudoers_path" ] || { echo "refusing sudoers symlink: $sudoers_path" >&2; exit 1; }
tmp="$(mktemp "$sudoers_dir/.90-chrootctl-user.XXXXXX")"
cleanup() { rm -f "$tmp"; }
trap cleanup EXIT HUP INT TERM
chmod 440 "$tmp"
printf '%%%s ALL=(ALL:ALL) ALL\n' "$group_name" >"$tmp"
visudo -cf "$tmp" >/dev/null
mv -f "$tmp" "$sudoers_path"
chmod 440 "$sudoers_path"
trap - EXIT HUP INT TERM

echo "User ${user_name} is ready for sudo through group ${group_name}."
