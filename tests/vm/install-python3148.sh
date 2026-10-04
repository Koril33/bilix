#!/bin/bash
# Build the exact CPython release until uv's standalone index includes it.
# The SHA256 value comes from python.org's 3.14.8 release page.
set -euo pipefail

version=3.14.8
archive="Python-$version.tar.xz"
expected_sha256=c2215904f02b175596dc49351585104f4bc20341e1c47378b26a2c274360ce73
cache=/home/vagrant/.cache/bilix-python
host_cache=/bilix-host/dist/gui/cache
prefix="/home/vagrant/.local/python-$version"
python="$prefix/bin/python3.14"

if [ -x "$python" ] && [ "$("$python" --version)" = "Python $version" ]; then
    printf '%s\n' "$python"
    exit 0
fi

mkdir -p "$cache"
cd "$cache"
if [ -f "$archive" ] && ! printf '%s  %s\n' "$expected_sha256" "$archive" | sha256sum --check; then
    rm -f "$archive"
fi
if [ ! -f "$archive" ] && [ -f "$host_cache/$archive" ]; then
    cp "$host_cache/$archive" "$archive"
fi
if [ ! -f "$archive" ]; then
    curl --fail --location --retry 3 --connect-timeout 20 --max-time 300 \
        --output "$archive" "https://www.python.org/ftp/python/$version/$archive"
fi
printf '%s  %s\n' "$expected_sha256" "$archive" | sha256sum --check
tar -xf "$archive"
cd "Python-$version"
if [ ! -f Makefile ]; then
    LDFLAGS="-Wl,-rpath,$prefix/lib" ./configure \
        --prefix="$prefix" --enable-shared --with-ensurepip=install --disable-test-modules
fi
make -j4
make install
cp LICENSE "$prefix/LICENSE"
"$python" -c 'import _ssl, _ctypes, zlib, sqlite3; print("Python build modules OK")'
test "$("$python" --version)" = "Python $version"
printf '%s\n' "$python"
