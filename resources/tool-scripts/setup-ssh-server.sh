#!/bin/sh
set -eu

case "${CHROOTCTL_DISTRO:?}" in
  ubuntu)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y openssh-server
    ;;
  arch)
    pacman -Sy --noconfirm --needed openssh
    ;;
  *)
    echo "unsupported distro: ${CHROOTCTL_DISTRO}" >&2
    exit 1
    ;;
esac

ssh-keygen -A
mkdir -p /etc/ssh/sshd_config.d
cat >/etc/ssh/sshd_config.d/99-chrootctl.conf <<'EOF'
PermitRootLogin prohibit-password
PasswordAuthentication yes
UsePAM yes
X11Forwarding yes
EOF

echo "OpenSSH server installed. Review /etc/ssh/sshd_config.d/99-chrootctl.conf and enable/start sshd in the service manager that owns the chroot."
