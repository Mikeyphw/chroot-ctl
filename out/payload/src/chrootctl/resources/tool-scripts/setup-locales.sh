#!/bin/sh
set -eu

locale_name="${CHROOTCTL_LOCALE:-en_US.UTF-8}"
timezone_name="${CHROOTCTL_TIMEZONE:-UTC}"

case "${CHROOTCTL_DISTRO:?}" in
  ubuntu)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y locales tzdata
    if ! grep -q "^${locale_name} UTF-8$" /etc/locale.gen; then
      printf '\n%s UTF-8\n' "$locale_name" >> /etc/locale.gen
    fi
    locale-gen "$locale_name"
    update-locale LANG="$locale_name"
    ;;
  arch)
    pacman -Sy --noconfirm --needed glibc tzdata
    if ! grep -q "^${locale_name} UTF-8$" /etc/locale.gen; then
      printf '\n%s UTF-8\n' "$locale_name" >> /etc/locale.gen
    fi
    locale-gen
    printf 'LANG=%s\n' "$locale_name" >/etc/locale.conf
    ;;
  *)
    echo "unsupported distro: ${CHROOTCTL_DISTRO}" >&2
    exit 1
    ;;
esac

if [ -e "/usr/share/zoneinfo/${timezone_name}" ]; then
  ln -snf "/usr/share/zoneinfo/${timezone_name}" /etc/localtime
  printf '%s\n' "$timezone_name" >/etc/timezone
fi

echo "Locale set to ${locale_name}; timezone set to ${timezone_name}."
