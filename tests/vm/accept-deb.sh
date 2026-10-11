#!/bin/bash
set -euo pipefail

target="${1:?target name required}"
expected="$(cat /etc/bilix-validation-target)"
if [ "$target" = ubuntu2204 ]; then
    test "$expected" = target=ubuntu2204clean
else
    test "$expected" = "target=$target"
fi
run_id="$(date -u +%Y%m%dT%H%M%SZ)-$$"
record_root="/home/vagrant/bilix-records/$target/$run_id"
host_records="/bilix-host/dist/gui/validation/$target/$run_id"
mkdir -p "$record_root" "$host_records"
finish() {
    code=$?
    printf 'exit_code=%s\n' "$code" > "$record_root/exit-code.txt"
    cp -a "$record_root/." "$host_records/" 2>/dev/null || true
}
trap finish EXIT
cp /etc/os-release "$record_root/os-release.txt"
deb="$(realpath "${2:?pass the exact deb selected from its release manifest}")"
case "$deb" in /bilix-host/dist/*/djhx-bilix-gui_*_amd64.deb) ;; *) exit 1 ;; esac
test -f "$deb"
artifact_root="$(dirname "$deb")"
package_version="$(dpkg-deb -f "$deb" Version)"
test "$(dpkg-deb -f "$deb" Package)" = djhx-bilix-gui
test "$(dpkg-deb -f "$deb" Architecture)" = amd64
printf '%s\n' "$package_version" > "$record_root/package-version.txt"
sha256sum "$deb" | tee "$record_root/deb-sha256.txt"
(
    cd "$artifact_root"
    if [ -f SHA256SUMS-linux.txt ]; then
        checksum_file=SHA256SUMS-linux.txt
    else
        checksum_file=SHA256SUMS.txt
    fi
    # The combined release list may be written on Windows. Normalize only the
    # checksum input's CRLF, never the immutable artifacts or original list.
    sed 's/\r$//' "$checksum_file" | sha256sum -c -
) 2>&1 | tee "$record_root/manifest-check.txt"

# No build dependencies are preinstalled in acceptance VMs. apt must be able to
# resolve every declared runtime dependency using that distro's own repository.
sudo apt-get update 2>&1 | tee "$record_root/apt-update.log"
sudo apt-get install -y "$deb" 2>&1 | tee "$record_root/apt-install.log"
dpkg-query -W -f='${Package} ${Version} ${Status}\n' djhx-bilix-gui \
    | tee "$record_root/dpkg-installed.txt"
test -x /usr/bin/bilix-gui
test -f /usr/share/applications/djhx-bilix-gui.desktop
test -f /usr/share/icons/hicolor/scalable/apps/djhx-bilix-gui.svg

profile="$record_root/profile"
downloads="$record_root/downloads"
mkdir -p "$profile" "$downloads"
printf 'retained-across-package-lifecycle\n' > "$profile/keep.txt"
printf 'download-retained\n' > "$downloads/keep.txt"
printf 'download_dir = "%s"\n' "$downloads" > "$profile/config.toml"
config_digest="$(sha256sum "$profile/config.toml")"
printf 'validation-placeholder-no-real-credentials\n' > "$profile/token.txt"
token_digest="$(sha256sum "$profile/token.txt")"
export BILIX_CONFIG_DIR="$profile"
export BILIX_DOWNLOAD_DIR="$downloads"
export QT_QPA_PLATFORM=offscreen
/usr/bin/bilix-gui --smoke-test 2>&1 | tee "$record_root/offscreen-smoke.txt"

# xcb smoke exercises a real X server without needing a user login. It does not
# replace a visible desktop/IME/file-picker inspection.
unset QT_QPA_PLATFORM
xvfb-run -a /usr/bin/bilix-gui --smoke-test 2>&1 | tee "$record_root/xvfb-smoke.txt"

prior="${3:-}"
if [ -n "$prior" ]; then
    prior="$(realpath "$prior")"
    test "$(dpkg-deb -f "$prior" Package)" = djhx-bilix-gui
    prior_version="$(dpkg-deb -f "$prior" Version)"
    dpkg --compare-versions "$prior_version" lt "$package_version"
    sha256sum "$prior" | tee "$record_root/prior-deb-sha256.txt"
    # Exercise APT's own downgrade policy before the genuine old-to-new upgrade.
    if sudo apt-get install -y "$prior" > "$record_root/apt-downgrade-rejected.log" 2>&1; then
        echo 'APT unexpectedly accepted unattended downgrade without --allow-downgrades' >&2
        exit 1
    fi
    sudo apt-get install -y --allow-downgrades "$prior" 2>&1 | tee "$record_root/apt-prior-install.log"
    test "$(dpkg-query -W -f='${Version}' djhx-bilix-gui)" = "$prior_version"
    xvfb-run -a /usr/bin/bilix-gui --smoke-test 2>&1 | tee "$record_root/prior-smoke.txt"
    sudo apt-get install -y "$deb" 2>&1 | tee "$record_root/apt-upgrade.log"
    test "$(dpkg-query -W -f='${Version}' djhx-bilix-gui)" = "$package_version"
    test "$(sha256sum "$profile/config.toml")" = "$config_digest"
    test "$(sha256sum "$profile/token.txt")" = "$token_digest"
    test "$(cat "$downloads/keep.txt")" = download-retained
    xvfb-run -a /usr/bin/bilix-gui --smoke-test 2>&1 | tee "$record_root/upgrade-smoke.txt"
fi

# Reinstallation verifies a repeatable package transaction; genuine cross-
# version upgrade requires a previously published GUI release package.
sudo apt-get install -y --reinstall "$deb" 2>&1 | tee "$record_root/apt-reinstall.log"
test "$(cat "$profile/keep.txt")" = retained-across-package-lifecycle
test "$(cat "$downloads/keep.txt")" = download-retained
test "$(sha256sum "$profile/config.toml")" = "$config_digest"
test "$(sha256sum "$profile/token.txt")" = "$token_digest"
xvfb-run -a /usr/bin/bilix-gui --smoke-test 2>&1 | tee "$record_root/reinstall-smoke.txt"
sudo apt-get remove -y djhx-bilix-gui 2>&1 | tee "$record_root/apt-remove.log"
test ! -e /usr/bin/bilix-gui
test "$(cat "$profile/keep.txt")" = retained-across-package-lifecycle
test "$(cat "$downloads/keep.txt")" = download-retained
test "$(sha256sum "$profile/config.toml")" = "$config_digest"
test "$(sha256sum "$profile/token.txt")" = "$token_digest"
dpkg-query -W -f='${Status}\n' djhx-bilix-gui 2>/dev/null \
    | tee "$record_root/dpkg-removed.txt" || true
printf 'accept_success=1\n' | tee "$record_root/result.txt"
