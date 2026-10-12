"""Deploy the verified project homepage atomically using the bilix SSH account."""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import uuid
from pathlib import Path

REMOTE_HOST = "bilix@djhx.site"
REMOTE_ROOT = "/var/www/bilix.djhx.site"
ROOT = Path(__file__).resolve().parents[1]

# This runs as bilix, without sudo. Staging and backup remain in the project root.
REMOTE_COMMIT = r"""
import hashlib, json, os, stat, sys
from datetime import datetime, timezone
from pathlib import Path
p = json.loads(sys.stdin.read())
root = Path("/var/www/bilix.djhx.site")
if root.resolve() != root or not root.is_dir():
    raise RuntimeError("Unexpected website root")
if os.getuid() == 0 or __import__("pwd").getpwuid(os.getuid()).pw_name != "bilix":
    raise RuntimeError("Website deployment must run as bilix")
stage = root / p["staging"]
if stage.parent != root or not stage.name.startswith(".site-staging-"):
    raise RuntimeError("Invalid staging path")
fd = os.open(stage, os.O_RDONLY | os.O_NOFOLLOW)
with os.fdopen(fd, "rb") as stream:
    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
        raise RuntimeError("Staging page is not a regular file")
    raw = stream.read(4 * 1024 * 1024 + 1)
if len(raw) != p["bytes"] or hashlib.sha256(raw).hexdigest() != p["sha256"]:
    raise RuntimeError("Uploaded page differs from reviewed page")
lock = root / ".site-deploy-lock"
lock.mkdir()
try:
    target = root / "index.html"
    if not target.is_file() or target.is_symlink():
        raise RuntimeError("Unexpected current homepage")
    previous = target.read_bytes()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = root / ("index.html.before-" + timestamp + "-" + p["token"])
    with backup.open("xb") as stream:
        stream.write(previous)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(backup, 0o644)
    # Rewrite verified bytes rather than trusting a mutable uploaded path.
    final_stage = root / (".site-verified-" + p["token"])
    with final_stage.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(final_stage, 0o644)
    os.replace(final_stage, target)
    directory_fd = os.open(root, os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    if hashlib.sha256(target.read_bytes()).hexdigest() != p["sha256"]:
        raise RuntimeError("Deployed page hash differs")
    stage.unlink()
    print(json.dumps({"account":"bilix", "sha256":p["sha256"], "backup":str(backup)}))
finally:
    lock.rmdir()
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-file", type=Path, default=ROOT / "site/bilix.html")
    parser.add_argument("--ssh-key", type=Path, required=True)
    parser.add_argument("--check", action="store_true", help="Check identity and permissions only")
    args = parser.parse_args()
    options = ["-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-i", str(args.ssh_key)]
    check = (
        'set -eu; test "$(id -un)" = bilix; '
        f'test "$(readlink -f {REMOTE_ROOT})" = {REMOTE_ROOT}; '
        f"test -w {REMOTE_ROOT}; test -w {REMOTE_ROOT}/index.html; "
        f"stat -c '%U:%G %a %n' {REMOTE_ROOT} {REMOTE_ROOT}/index.html"
    )
    subprocess.run(["ssh", *options, REMOTE_HOST, check], check=True)
    if args.check:
        return
    raw = args.site_file.read_bytes()
    if not 0 < len(raw) <= 4 * 1024 * 1024:
        raise ValueError("Homepage must contain 1 byte to 4 MiB")
    text = raw.decode("utf-8")
    if "<!doctype html" not in text.lower() or "BiliX" not in text:
        raise ValueError("Expected the BiliX HTML homepage")
    token = uuid.uuid4().hex
    staging = ".site-staging-" + token
    subprocess.run(
        ["scp", *options, str(args.site_file), f"{REMOTE_HOST}:{REMOTE_ROOT}/{staging}"],
        check=True,
    )
    request = {
        "staging": staging,
        "token": token,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    subprocess.run(
        ["ssh", *options, REMOTE_HOST, "python3 -c " + shlex.quote(REMOTE_COMMIT)],
        input=json.dumps(request),
        text=True,
        check=True,
    )


if __name__ == "__main__":
    main()
