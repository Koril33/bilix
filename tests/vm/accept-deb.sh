#!/bin/bash
set -euo pipefail

target="${1:?target name required}"
expected="$(cat /etc/bilix-validation-target)"
if [ "$target" = ubuntu2204 ]; then
    test "$expected" = target=ubuntu2204clean
else
    test "$expected" = "target=$target"
fi
record_root="/home/vagrant/bilix-records/$target"
mkdir -p "$record_root"
mkdir -p "/bilix-host/dist/gui/validation/$target"
trap 'cp -a "$record_root/." "/bilix-host/dist/gui/validation/$target/" 2>/dev/null || true' EXIT
cp /etc/os-release "$record_root/os-release.txt"
mapfile -t packages < <(find /bilix-host/dist/gui -maxdepth 1 -name 'djhx-bilix-gui_*_amd64.deb' -type f)
if [ "${#packages[@]}" -ne 1 ]; then
    printf 'Expected exactly one GUI deb; found %s\n' "${#packages[@]}" >&2
    exit 1
fi
deb="${packages[0]}"
sha256sum "$deb" | tee "$record_root/deb-sha256.txt"
(
    cd /bilix-host/dist/gui
    sha256sum -c SHA256SUMS-linux.txt
) 2>&1 | tee "$record_root/manifest-check.txt"

# No build dependencies are preinstalled in acceptance VMs. apt must be able to
# resolve every declared runtime dependency using that distro's own repository.
sudo apt-get install -y "$deb" 2>&1 | tee "$record_root/apt-install.log"
dpkg-query -W -f='${Package} ${Version} ${Status}\n' djhx-bilix-gui \
    | tee "$record_root/dpkg-installed.txt"
test -x /usr/bin/bilix-gui
test -f /usr/share/applications/djhx-bilix-gui.desktop
test -f /usr/share/icons/hicolor/scalable/apps/djhx-bilix-gui.svg

profile="/home/vagrant/bilix-validation-profile-$target"
mkdir -p "$profile" "/home/vagrant/bilix-downloads-$target"
printf 'retained-across-package-lifecycle\n' > "$profile/keep.txt"
export BILIX_CONFIG_DIR="$profile"
export BILIX_DOWNLOAD_DIR="/home/vagrant/bilix-downloads-$target"
export QT_QPA_PLATFORM=offscreen
/usr/bin/bilix-gui --smoke-test 2>&1 | tee "$record_root/offscreen-smoke.txt"

# xcb smoke exercises a real X server without needing a user login. It does not
# replace a visible desktop/IME/file-picker inspection.
unset QT_QPA_PLATFORM
xvfb-run -a /usr/bin/bilix-gui --smoke-test 2>&1 | tee "$record_root/xvfb-smoke.txt"

# Reinstallation verifies a repeatable package transaction; genuine cross-
# version upgrade requires a previously published GUI release package.
sudo apt-get install -y --reinstall "$deb" 2>&1 | tee "$record_root/apt-reinstall.log"
test "$(cat "$profile/keep.txt")" = retained-across-package-lifecycle
xvfb-run -a /usr/bin/bilix-gui --smoke-test 2>&1 | tee "$record_root/reinstall-smoke.txt"
sudo apt-get remove -y djhx-bilix-gui 2>&1 | tee "$record_root/apt-remove.log"
test ! -e /usr/bin/bilix-gui
test "$(cat "$profile/keep.txt")" = retained-across-package-lifecycle
dpkg-query -W -f='${Status}\n' djhx-bilix-gui 2>/dev/null \
    | tee "$record_root/dpkg-removed.txt" || true
printf 'accept_success=1\n' | tee "$record_root/result.txt"
