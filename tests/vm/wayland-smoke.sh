#!/bin/bash
# Optional Wayland protocol smoke test using a disposable headless Weston.
set -euo pipefail

target="${1:?target name required}"
record_root="/home/vagrant/bilix-records/$target"
mkdir -p "$record_root" "/bilix-host/dist/gui/validation/$target"
trap 'cp -a "$record_root/." "/bilix-host/dist/gui/validation/$target/" 2>/dev/null || true' EXIT

runtime_dir="$(mktemp -d /tmp/bilix-wayland.XXXXXX)"
chmod 700 "$runtime_dir"
export XDG_RUNTIME_DIR="$runtime_dir"
export WAYLAND_DISPLAY=bilix-wayland
weston --backend=headless-backend.so --socket="$WAYLAND_DISPLAY" \
    --idle-time=0 --log="$record_root/weston.log" \
    >"$record_root/weston-stdout.log" 2>&1 &
weston_pid=$!
cleanup() {
    kill "$weston_pid" 2>/dev/null || true
    wait "$weston_pid" 2>/dev/null || true
    rm -rf -- "$runtime_dir"
}
trap 'cleanup; cp -a "$record_root/." "/bilix-host/dist/gui/validation/$target/" 2>/dev/null || true' EXIT

for _ in $(seq 1 40); do
    if [ -S "$runtime_dir/$WAYLAND_DISPLAY" ]; then
        break
    fi
    if ! kill -0 "$weston_pid" 2>/dev/null; then
        cat "$record_root/weston.log" >&2
        exit 1
    fi
    sleep 0.25
done
test -S "$runtime_dir/$WAYLAND_DISPLAY"
QT_QPA_PLATFORM=wayland /usr/bin/bilix-gui --smoke-test \
    2>&1 | tee "$record_root/wayland-smoke.txt"
