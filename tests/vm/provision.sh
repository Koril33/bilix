#!/bin/sh
set -eu

target="$1"
export DEBIAN_FRONTEND=noninteractive
# Older Debian boxes use a redirector that can make sequential apt downloads
# very slow. Keep the official repositories, using their HTTPS CDN directly.
if [ -f /etc/apt/sources.list ]; then
    sed -i \
        -e 's@http://httpredir.debian.org/debian/@https://deb.debian.org/debian/@g' \
        -e 's@http://security.debian.org/debian-security@https://security.debian.org/debian-security@g' \
        -e 's/^deb-src /# bilix validation: deb-src /' \
        /etc/apt/sources.list
fi
printf 'Acquire::Languages "none";\n' > /etc/apt/apt.conf.d/99bilix-validation
apt-get update -qq
apt-get install -y --no-install-recommends ca-certificates curl tar xz-utils xvfb xauth
if [ "$target" = ubuntu2204 ]; then
    apt-get install -y --no-install-recommends build-essential binutils dpkg-dev patchelf ffmpeg \
        libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev \
        libffi-dev liblzma-dev libgdbm-dev libncursesw5-dev uuid-dev \
        libegl1 libgl1 libdbus-1-3 libfontconfig1 libx11-xcb1 \
        libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-image0 \
        libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 \
        libxcb-xinerama0 libxcb-xkb1
fi

printf 'target=%s\n' "$target" > /etc/bilix-validation-target
