#!/bin/sh
# Run on the maintainer's Linux workstation/VM. Only public/ is uploaded to Nginx.
set -eu
if [ "$#" -ne 3 ]; then
    echo "Usage: GNUPGHOME=/private/outside-repo scripts/publish_apt.sh DEB WORKDIR GPG_FINGERPRINT" >&2
    exit 2
fi
deb=$(realpath "$1")
work=$(realpath -m "$2")
key=$3
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
: "${GNUPGHOME:?Set a protected GNUPGHOME outside the source repository}"
keyhome=$(realpath "$GNUPGHOME")
case "$keyhome/" in "$project/"*) echo "GPG private keys must stay outside the repository" >&2; exit 2;; esac
case "$work/" in "$keyhome/"*) echo "APT public output must be separate from GNUPGHOME" >&2; exit 2;; esac
case "$keyhome/" in "$work/public/"*) echo "GNUPGHOME cannot be inside APT public output" >&2; exit 2;; esac
case "$key" in *[!A-Fa-f0-9]*|'') echo "Use the full GPG fingerprint" >&2; exit 2;; esac
if [ "${#key}" -ne 40 ] && [ "${#key}" -ne 64 ]; then
    echo "Use the full GPG fingerprint" >&2
    exit 2
fi
[ "$(dpkg-deb -f "$deb" Package)" = djhx-bilix-gui ]
[ "$(dpkg-deb -f "$deb" Architecture)" = amd64 ]
package_version=$(dpkg-deb -f "$deb" Version)
mkdir -p "$work"
chmod 700 "$keyhome"
config="$work/aptly.conf"
python3 - "$config" "$work" <<'PY'
import json, sys
with open(sys.argv[1], "w", encoding="utf-8") as stream:
    json.dump({"rootDir": sys.argv[2], "architectures": ["amd64"]}, stream)
PY
if ! aptly -config="$config" repo show bilix-stable >/dev/null 2>&1; then
    aptly -config="$config" repo create -distribution=stable -component=main bilix-stable
fi
aptly -config="$config" repo add bilix-stable "$deb"
snapshot="bilix-$package_version"
aptly -config="$config" snapshot create "$snapshot" from repo bilix-stable
if [ -f "$work/public/dists/stable/Release" ]; then
    aptly -config="$config" publish switch -gpg-key="$key" -skip-cleanup stable . "$snapshot"
else
    # filesystem endpoint is not needed: aptly's standard public/ output serves Nginx.
    aptly -config="$config" publish snapshot -distribution=stable -component=main -architectures=amd64 \
        -acquire-by-hash -gpg-key="$key" "$snapshot"
fi
mkdir -p "$work/public/keys"
gpg --armor --export "$key" > "$work/public/keys/bilix-archive-key.asc"
gpg --verify "$work/public/dists/stable/InRelease"
echo "Signed APT snapshot prepared at $work/public; upload contents to /var/www/bilix.djhx.site/apt/"
