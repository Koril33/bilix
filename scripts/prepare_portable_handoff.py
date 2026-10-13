"""Create an offline signed portable transaction fixture, never a public release.

The fixture may use the test executable's own version: it exercises handoff,
replacement and restart, not UpdateClient's public-network version discovery.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from update_release import key_record, sign_bytes

from djhx_bilix.updater.protocol import (
    encode_json,
    release_urls,
    sha256,
    trusted_keys,
    verify_bundle,
    version,
)


def prepare_fixture(package: Path, app_version: str, private: Path, output: Path) -> dict:
    version(app_version)
    package = package.resolve(strict=True)
    private = private.resolve(strict=True)
    output = output.resolve()
    if not package.is_file() or package.suffix.lower() != ".exe":
        raise ValueError("Package must be an existing production portable EXE")
    if output == package.parent or output.exists():
        raise ValueError("Use a fresh fixture directory separate from the package directory")

    key = Ed25519PrivateKey.from_private_bytes(private.read_bytes())
    key_id, public = key_record(key)
    keys = trusted_keys()
    if keys.get(key_id) != public:
        raise ValueError("Signing key does not match the embedded update trust root")
    package_hash = sha256(package)
    package_size = package.stat().st_size
    tag = f"v{app_version}"
    name = f"BiliX-GUI-Portable-{app_version}-windows-x64.exe"
    stamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    manifest = {
        "schema": 1,
        "product": "bilix",
        "channel": "stable",
        "version": app_version,
        "release_tag": tag,
        "published_at": stamp,
        "min_updater_schema": 1,
        "config_compatibility": "backup-before-migration",
        "release_notes_url": f"https://github.com/Koril33/bilix/releases/tag/{tag}",
        "artifacts": [
            {
                "artifact_id": "windows-x64-portable",
                "platform": "windows",
                "arch": "x64",
                "package_type": "portable",
                "install_scope": "user",
                "package_version": app_version,
                "filename": name,
                "bytes": package_size,
                "sha256": package_hash,
                "urls": release_urls(tag, name),
                "os_constraints": {"windows_min": 10},
            }
        ],
    }
    manifest_raw = encode_json(manifest)
    channel_raw = encode_json(
        {
            "schema": 1,
            "product": "bilix",
            "channel": "stable",
            "version": app_version,
            "release_tag": tag,
            "issued_at": stamp,
            "metadata_sequence": 1,
            "manifest_bytes": len(manifest_raw),
            "manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
            "manifest_urls": release_urls(tag, "update-manifest.json"),
        }
    )
    blobs = {
        "stable.json": channel_raw,
        "stable.json.sig": sign_bytes(key, channel_raw),
        "update-manifest.json": manifest_raw,
        "update-manifest.json.sig": sign_bytes(key, manifest_raw),
    }
    _, artifact = verify_bundle(blobs, "windows-x64-portable", keys)
    output.mkdir(parents=True, exist_ok=False)
    copied = output / name
    shutil.copy2(package, copied)
    artifact.verify_file(copied)
    if sha256(package) != package_hash:
        raise ValueError("Source package changed while the fixture was being prepared")
    for filename, raw in blobs.items():
        (output / filename).write_bytes(raw)
    record = {
        "schema": 1,
        "scope": "offline-signed-portable-transaction",
        "public_network_discovery": False,
        "version": app_version,
        "package_sha256": package_hash,
        "package_bytes": package_size,
    }
    (output / "fixture.json").write_bytes(encode_json(record))
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    record = prepare_fixture(args.package, args.version, args.private_key, args.output)
    print(
        f"Prepared offline portable handoff fixture {record['version']}: {args.output.resolve()}"
        " (not public-network version discovery)"
    )


if __name__ == "__main__":
    main()
