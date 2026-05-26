#!/bin/sh
set -eu

case "${CHROOTCTL_DISTRO:?}" in
  ubuntu)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y bindfs fuse3
    ;;
  arch)
    pacman -Sy --noconfirm --needed bindfs fuse3
    ;;
  *)
    echo "unsupported distro: ${CHROOTCTL_DISTRO}" >&2
    exit 1
    ;;
esac

mkdir -p /mnt/shared /media/shared /usr/local/bin
cat >/usr/local/bin/chrootctl-shared-folders <<'EOF'
#!/bin/sh
set -eu
mkdir -p /mnt/shared /media/shared
echo "Mount host paths onto /mnt/shared or /media/shared with bind mounts or bindfs."
EOF
chmod +x /usr/local/bin/chrootctl-shared-folders

echo "Shared-folder helpers installed."
