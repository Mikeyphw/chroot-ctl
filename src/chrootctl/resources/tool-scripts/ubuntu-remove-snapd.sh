#!/bin/sh
set -eu

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get -y purge firefox snapd || true
rm -rf /snap /var/cache/snapd /var/lib/snapd /var/snap /root/snap "/home/${CHROOTCTL_USERNAME}/snap" || true

mkdir -p /etc/apt/preferences.d /etc/apt/apt.conf.d
cat >/etc/apt/preferences.d/nosnap.pref <<'EOF'
Package: snapd
Pin: release a=*
Pin-Priority: -10
EOF

cat >/etc/apt/apt.conf.d/99chrootctl-no-snapd <<'EOF'
APT::NeverAutoRemove:: "^snapd$";
EOF

apt-mark hold snapd || true
echo "snapd removed and pinned."
