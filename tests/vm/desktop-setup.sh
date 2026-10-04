#!/bin/sh
# Optional visible X11 desktop for release-candidate UI inspection.
set -eu
export DEBIAN_FRONTEND=noninteractive
printf 'lightdm shared/default-x-display-manager select lightdm\n' | debconf-set-selections
apt-get update
apt-get install -y --no-install-recommends \
    xfce4 lightdm lightdm-gtk-greeter xserver-xorg dbus-x11 \
    fonts-noto-cjk xdotool xclip
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
