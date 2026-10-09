#!/bin/sh
# Visible desktop/IME prerequisites for this repository's dedicated test VMs.
# Does not start/restart a display manager or reboot the VM.
set -eu

[ "$(id -u)" = 0 ] || { echo 'Run this setup as root in a dedicated test VM' >&2; exit 1; }
marker=$(cat /etc/bilix-validation-target)
. /etc/os-release
case "$marker:$ID:$VERSION_ID" in
    target=ubuntu2204:ubuntu:22.04|target=ubuntu2204clean:ubuntu:22.04|\
    target=ubuntu2404:ubuntu:24.04|target=debian12:debian:12|target=debian13:debian:13) ;;
    *) echo 'Refusing desktop changes outside the supported dedicated VM marker/OS' >&2; exit 1 ;;
esac
[ "$(dpkg --print-architecture)" = amd64 ]
[ "$(getent passwd vagrant | cut -d: -f6)" = /home/vagrant ]

# Some minimal boxes ship an empty legacy DBus ID; Qt and IBus must discover
# the same valid machine ID. Repair only the known empty file in this test VM.
if [ -f /var/lib/dbus/machine-id ] && [ ! -s /var/lib/dbus/machine-id ]; then
    grep -Eq '^[0-9a-f]{32}$' /etc/machine-id
    cp /etc/machine-id /var/lib/dbus/machine-id
fi

export DEBIAN_FRONTEND=noninteractive
printf 'lightdm shared/default-x-display-manager select lightdm\n' | debconf-set-selections
apt-get update
apt-get install -y --no-install-recommends \
    xfce4 xfconf lightdm lightdm-gtk-greeter xserver-xorg dbus-x11 kbd \
    fonts-noto-cjk fontconfig xdotool xclip x11-utils x11-xserver-utils \
    ibus ibus-libpinyin ibus-gtk3 im-config

mkdir -p /etc/lightdm/lightdm.conf.d
cat > /etc/lightdm/lightdm.conf.d/50-bilix-validation.conf <<'EOF'
[Seat:*]
autologin-user=vagrant
autologin-user-timeout=0
autologin-session=xfce
user-session=xfce
EOF
systemctl enable lightdm
systemctl set-default graphical.target
printf 'Desktop prerequisites ready for %s; maintainer starts the visible X11 session.\n' "$marker"
dpkg-query -W -f='${Package} ${Version}\n' \
    xfce4 lightdm fonts-noto-cjk ibus ibus-libpinyin xdotool xclip
