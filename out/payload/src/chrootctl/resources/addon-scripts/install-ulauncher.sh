#!/bin/sh
set -eu

if [ "${CHROOTCTL_DISTRO:?}" != "ubuntu" ]; then
  echo "unsupported distro: ${CHROOTCTL_DISTRO}" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y software-properties-common ca-certificates
add-apt-repository -y ppa:agornostal/ulauncher || true
apt-get update
apt-get install -y ulauncher
