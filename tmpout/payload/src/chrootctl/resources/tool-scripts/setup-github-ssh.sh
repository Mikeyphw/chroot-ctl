#!/bin/sh
set -eu

case "${CHROOTCTL_DISTRO:?}" in
  ubuntu)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y openssh-client ca-certificates
    ;;
  arch)
    pacman -Sy --noconfirm --needed openssh ca-certificates
    ;;
  *)
    echo "unsupported distro: ${CHROOTCTL_DISTRO}" >&2
    exit 1
    ;;
esac

user_name="${CHROOTCTL_USERNAME:-root}"
user_home="/root"
if [ "$user_name" != "root" ] && [ -d "/home/$user_name" ]; then
  user_home="/home/$user_name"
fi

mkdir -p "$user_home/.ssh"
chmod 700 "$user_home/.ssh"

key_path="$user_home/.ssh/id_ed25519"
if [ ! -f "$key_path" ]; then
  ssh-keygen -t ed25519 -N "" -C "${user_name}@${CHROOTCTL_NAME}" -f "$key_path"
fi

known_hosts="$user_home/.ssh/known_hosts"
touch "$known_hosts"
chmod 600 "$known_hosts"
if command -v ssh-keyscan >/dev/null 2>&1; then
  ssh-keyscan -t ed25519 github.com 2>/dev/null >>"$known_hosts" || true
fi

config_path="$user_home/.ssh/config"
if [ ! -f "$config_path" ] || ! grep -q '^Host github\.com$' "$config_path"; then
  cat >>"$config_path" <<'EOF'
Host github.com
  HostName github.com
  User git
  IdentityFile ~/.ssh/id_ed25519
  IdentitiesOnly yes
EOF
fi
chmod 600 "$config_path"

if id "$user_name" >/dev/null 2>&1; then
  chown -R "$user_name:$user_name" "$user_home/.ssh"
fi

echo "Public key:"
cat "${key_path}.pub"
