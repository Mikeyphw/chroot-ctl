#!/bin/sh
set -eu

if [ "${CHROOTCTL_DISTRO:?}" != "ubuntu" ]; then
  echo "ulauncher is currently packaged as an Ubuntu-only addon." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y software-properties-common ca-certificates
add-apt-repository -y ppa:agornostal/ulauncher || true
apt-get update
apt-get install -y ulauncher
