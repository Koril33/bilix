"""Verify and mirror a signed release, switching stable only after artifact checks."""

from __future__ import annotations

import argparse
import hashlib
import shlex
import subprocess
import uuid
from pathlib import Path

from update_release import verified_collection

from djhx_bilix.updater.client import BUNDLE_NAMES
from djhx_bilix.updater.protocol import (
    filename,
    read_json,
    sha256,
    trusted_keys,
    validate_channel,
    verify_bundle,
    verify_signed,
)

REMOTE_ROOT = "/var/www/bilix.djhx.site"
REMOTE_HOST = "bilix@djhx.site"


def publish(directory: Path, ssh_key: Path) -> None:
    blobs = {name: (directory / name).read_bytes() for name in BUNDLE_NAMES}
    channel, _ = verify_bundle(blobs, "windows-x64-portable")
    for artifact_id in ("windows-x64-installer", "linux-amd64-deb"):
        verify_bundle(blobs, artifact_id)
    manifest = verify_signed(blobs["update-manifest.json"], blobs["update-manifest.json.sig"])
    names = [filename(item["filename"]) for item in manifest["artifacts"]]
    if len(set(names)) != len(names):
        raise RuntimeError("Signed manifest repeats an artifact")
    for item in manifest["artifacts"]:
        path = directory / item["filename"]
        if path.stat().st_size != item["bytes"] or sha256(path) != item["sha256"]:
            raise RuntimeError(f"Release file changed: {path.name}")
    final = verified_collection(directory)
    if {entry["name"] for entry in final["artifacts"]} != set(names):
        raise RuntimeError("Existing release collection differs from signed update manifest")
    files = [*names, *BUNDLE_NAMES, "release-manifest.json", "SHA256SUMS.txt", "update-keys.json"]
    if read_json((directory / "update-keys.json").read_bytes()).get("keys") != trusted_keys():
        raise RuntimeError("Published public key differs from the embedded trust root")
    token = uuid.uuid4().hex
    staging = f"{REMOTE_ROOT}/releases/.staging-{token}"
    destination = f"{REMOTE_ROOT}/releases/{channel['release_tag']}"
    lock = f"{REMOTE_ROOT}/updates/.publish-lock"
    options = ["-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-i", str(ssh_key)]

    def remote(command: str, *, check=True):
        return subprocess.run(
            ["ssh", *options, REMOTE_HOST, command], check=check, capture_output=True
        )

    checksums = directory / f"upload-sha256-{token}.txt"
    checksums.write_text(
        "".join(f"{sha256(directory / name)}  {name}\n" for name in files), encoding="ascii"
    )
    locked = False
    try:
        remote(f"mkdir {shlex.quote(lock)}")
        locked = True
        previous = remote(f"cat {shlex.quote(REMOTE_ROOT + '/updates/stable.json')}", check=False)
        if previous.returncode == 0:
            signature = remote(
                f"cat {shlex.quote(REMOTE_ROOT + '/updates/stable.json.sig')}"
            ).stdout
            old = validate_channel(verify_signed(previous.stdout, signature))
            validate_channel(
                channel,
                sequence=old["metadata_sequence"],
                previous_hash=hashlib.sha256(previous.stdout).hexdigest(),
                raw=blobs["stable.json"],
            )
        remote(f"test ! -e {shlex.quote(destination)} && mkdir {shlex.quote(staging)}")
        subprocess.run(
            ["scp", *options, *files, checksums.name, f"{REMOTE_HOST}:{staging}/"],
            cwd=directory,
            check=True,
        )
        remote(f"cd {shlex.quote(staging)} && sha256sum -c {shlex.quote(checksums.name)}")
        remote(
            f"test ! -e {shlex.quote(destination)} && "
            f"mv {shlex.quote(staging)} {shlex.quote(destination)}"
        )
        updates = f"{REMOTE_ROOT}/updates"
        commands = [f"mkdir -p {shlex.quote(updates + '/keys')}"]
        commands.append(
            "cp "
            + shlex.quote(destination + "/update-keys.json")
            + " "
            + shlex.quote(updates + "/keys/update-keys.json")
        )
        for name in ("stable.json", "stable.json.sig"):
            commands.append(
                "cp "
                + shlex.quote(destination + "/" + name)
                + " "
                + shlex.quote(updates + "/" + name + ".new-" + token)
            )
        for name in ("stable.json.sig", "stable.json"):
            commands.append(
                "mv "
                + shlex.quote(updates + "/" + name + ".new-" + token)
                + " "
                + shlex.quote(updates + "/" + name)
            )
        remote(" && ".join(commands))
        print(f"Mirrored and activated {channel['release_tag']} on https://bilix.djhx.site")
    finally:
        checksums.unlink(missing_ok=True)
        if locked:
            remote(f"rmdir {shlex.quote(lock)}", check=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--ssh-key", type=Path, required=True)
    args = parser.parse_args()
    publish(args.directory.resolve(), args.ssh_key.resolve())


if __name__ == "__main__":
    main()
