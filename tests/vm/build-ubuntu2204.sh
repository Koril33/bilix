#!/bin/bash
set -euo pipefail

source_root=/bilix-host
work_root=/home/vagrant/bilix-work
record_root=/home/vagrant/bilix-records
source_list="$source_root/dist/gui/cache/source-files.nul"
test "$(. /etc/os-release; printf '%s' "$ID:$VERSION_ID")" = ubuntu:22.04
test "$(cat /etc/bilix-validation-target)" = target=ubuntu2204
test -s "$source_list"
mkdir -p "$work_root" "$record_root" "$source_root/dist/gui"
mkdir -p "$source_root/dist/gui/validation/ubuntu2204-build"
trap 'cp -a "$record_root/." "$source_root/dist/gui/validation/ubuntu2204-build/" 2>/dev/null || true' EXIT

# Copy an explicit source list onto guest ext4. A VirtualBox shared folder is not
# suitable for Python build caches and can contain unrelated user credentials.
tar -C "$source_root" --exclude='*.exe' --exclude='__pycache__' \
    --exclude='*.pyc' --exclude='.vagrant' -cf - \
    src scripts tests docs pyproject.toml uv.lock .python-version README.md \
    CHANGELOG.md CONTRIBUTING.md SECURITY.md LICENSE THIRD_PARTY_NOTICES.md \
    | tar -C "$work_root" -xf -
cp "$source_list" "$work_root/.source-files.nul"
chown -R vagrant:vagrant "$work_root" "$record_root"

export PATH="/home/vagrant/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/home/vagrant/.local/bin sh
fi
uv --version | tee "$record_root/uv-version.txt"
python="$(bash "$source_root/tests/vm/install-python3148.sh" | tee "$record_root/python-build.log" | tail -n 1)"
"$python" --version | tee "$record_root/python-version.txt"

cd "$work_root"
export UV_CACHE_DIR=/home/vagrant/.cache/uv
export BILIX_SOURCE_FILE_LIST="$work_root/.source-files.nul"
sha256sum "$BILIX_SOURCE_FILE_LIST" | tee "$record_root/source-list-sha256.txt"
uv sync --python "$python" --locked --extra gui --group gui-test --group build \
    2>&1 | tee "$record_root/uv-sync.log"
QT_QPA_PLATFORM=offscreen uv run --locked --extra gui --group gui-test python -m pytest -q \
    2>&1 | tee "$record_root/pytest.log"
uv run --locked --extra gui --group gui-test ruff check src tests scripts \
    2>&1 | tee "$record_root/ruff-check.log"
uv run --locked --extra gui --group gui-test ruff format --check src tests scripts \
    2>&1 | tee "$record_root/ruff-format.log"
uv run --locked --extra gui --group build python scripts/build_gui_linux.py \
    2>&1 | tee "$record_root/build.log"
uv run --locked --extra gui --group build python scripts/package_gui_deb.py \
    --maintainer "${BILIX_DEB_MAINTAINER:-Koril <dingjinghui33@163.com>}" \
    2>&1 | tee "$record_root/package.log"
uv run --locked --extra gui --group build python tests/vm/verify-source-archive.py \
    dist/gui/*_source.tar.gz 2>&1 | tee "$record_root/source-audit.log"

find dist/gui -maxdepth 1 -type f \( -name '*.deb' -o -name '*source.tar.gz' -o -name 'SHA256SUMS-linux.txt' -o -name 'release-manifest-linux.json' \) \
    -exec cp -f {} "$source_root/dist/gui/" \;
sha256sum dist/gui/*.deb | tee "$record_root/deb-sha256.txt"
cp /etc/os-release "$record_root/os-release.txt"
cp build/gui/linux/smoke.txt "$record_root/standalone-smoke.txt"
printf 'build_success=1\n' | tee "$record_root/result.txt"
