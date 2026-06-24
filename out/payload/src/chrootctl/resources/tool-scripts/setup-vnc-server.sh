#!/bin/sh
set -eu

case "${CHROOTCTL_DISTRO:?}" in
  ubuntu)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y tigervnc-standalone-server tigervnc-common xauth dbus-x11 xterm
    ;;
  arch)
    pacman -Sy --noconfirm --needed tigervnc xorg-xauth dbus xterm
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

desktop_command="xterm"
if command -v startxfce4 >/dev/null 2>&1; then
  desktop_command="startxfce4"
elif command -v cinnamon-session >/dev/null 2>&1; then
  desktop_command="cinnamon-session"
elif command -v gnome-session >/dev/null 2>&1; then
  desktop_command="gnome-session"
fi

mkdir -p "$user_home/.vnc"
cat >"$user_home/.vnc/xstartup" <<EOF
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
exec ${desktop_command}
EOF
chmod 700 "$user_home/.vnc"
chmod +x "$user_home/.vnc/xstartup"

if id "$user_name" >/dev/null 2>&1; then
  chown -R "$user_name:$user_name" "$user_home/.vnc"
fi

echo "Run 'vncpasswd' as ${user_name}, then start the server with 'vncserver :1'."
