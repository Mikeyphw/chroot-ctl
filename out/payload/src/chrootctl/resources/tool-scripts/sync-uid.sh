#!/bin/sh
set -eu

case "${CHROOTCTL_DISTRO:?}" in
  ubuntu)
    ;;
  arch)
    ;;
  *)
    echo "unsupported distro: ${CHROOTCTL_DISTRO}" >&2
    exit 1
    ;;
esac

getent group "${CHROOTCTL_USERNAME}" >/dev/null 2>&1 || groupadd "${CHROOTCTL_USERNAME}"
id -u "${CHROOTCTL_USERNAME}" >/dev/null 2>&1 || useradd -m -s /bin/bash "${CHROOTCTL_USERNAME}"

host_uid="$(stat -c '%u' "/home/${CHROOTCTL_USERNAME}" 2>/dev/null || true)"
host_gid="$(stat -c '%g' "/home/${CHROOTCTL_USERNAME}" 2>/dev/null || true)"
if [ -z "${host_uid}" ] || [ -z "${host_gid}" ]; then
  echo "unable to infer uid/gid inside chroot for ${CHROOTCTL_USERNAME}" >&2
  exit 1
fi

groupmod -g "${host_gid}" "${CHROOTCTL_USERNAME}"
usermod -u "${host_uid}" -g "${host_gid}" "${CHROOTCTL_USERNAME}"
chown -R "${CHROOTCTL_USERNAME}:${CHROOTCTL_USERNAME}" "/home/${CHROOTCTL_USERNAME}"
