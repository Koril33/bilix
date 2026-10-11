"""Create an offline Ed25519 key or sign the final, verified release collection."""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from gui_release import ROOT

from djhx_bilix.updater.protocol import (
    ARTIFACT_IDS,
    ASSETS,
    encode_json,
    filename,
    read_json,
    release_tag,
    release_urls,
    select_artifact,
    sha256,
    trusted_keys,
    validate_channel,
    verify_bundle,
    version,
)


def key_record(key: Ed25519PrivateKey) -> tuple[str, str]:
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return "bilix-ed25519-" + hashlib.sha256(public).hexdigest()[:16], base64.b64encode(
        public
    ).decode()


def protect_private(path: Path) -> None:
    if os.name == "nt":
        user = subprocess.run(["whoami"], capture_output=True, text=True, check=True).stdout.strip()
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:(F)"],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    else:
        path.chmod(0o600)


def keygen(private: Path, backup: Path, public: Path) -> None:
    if public.exists():
        raise RuntimeError("Refusing to replace existing public trust roots")
    for path in (private, backup):
        resolved = path.resolve()
        if ROOT == resolved or ROOT in resolved.parents:
            raise RuntimeError("Private signing keys and backups must stay outside the repository")
        if path.exists():
            raise RuntimeError("Refusing to replace an existing signing key or backup")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if private.resolve() == backup.resolve() or public.resolve() in (
        private.resolve(),
        backup.resolve(),
    ):
        raise RuntimeError("Private, backup and public output must use different paths")
    key = Ed25519PrivateKey.generate()
    encoded = key.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    with private.open("xb") as stream:
        stream.write(encoded)
    protect_private(private)
    shutil.copy2(private, backup)
    protect_private(backup)
    key_id, public_value = key_record(key)
    public.parent.mkdir(parents=True, exist_ok=True)
    if public.exists():
        raise RuntimeError(
            "Refusing to overwrite public trust roots; merge deliberately for rotation"
        )
    public.write_bytes(encode_json({"format": 1, "keys": {key_id: public_value}}))
    print(f"Created private signing key and protected local backup; public key ID: {key_id}")


def sign_bytes(key: Ed25519PrivateKey, raw: bytes) -> bytes:
    key_id, _ = key_record(key)
    return encode_json(
        {
            "format": 1,
            "algorithm": "Ed25519",
            "key_id": key_id,
            "signature": base64.b64encode(key.sign(raw)).decode(),
        }
    )


def verified_collection(directory: Path) -> dict:
    final = read_json((directory / "release-manifest.json").read_bytes())
    app_version = final["version"]
    version(app_version)
    expected = {
        f"BiliX-GUI-Portable-{app_version}-windows-x64.exe",
        f"BiliX-GUI-Setup-{app_version}-windows-x64.exe",
        f"BiliX-GUI-licenses-and-source-{app_version}-windows-x64.zip",
        f"djhx-bilix-gui_{app_version}_source.tar.gz",
        f"djhx_bilix-{app_version}-py3-none-any.whl",
        f"djhx_bilix-{app_version}.tar.gz",
        f"bilix-{app_version}-windows-x64.zip",
    }
    records = final.get("artifacts")
    if not isinstance(records, list) or len(records) != 8:
        raise RuntimeError(
            "Sign the complete eight-file release collection, including sources/licenses"
        )
    names = [filename(entry["name"]) for entry in records]
    debs = {
        name
        for name in names
        if re.fullmatch(rf"djhx-bilix-gui_{re.escape(app_version)}-[1-9][0-9]*_amd64.deb", name)
    }
    if len(debs) != 1 or set(names) != expected | debs:
        raise RuntimeError("Release collection has missing, unexpected, or duplicate artifacts")
    for entry in records:
        path = directory / entry["name"]
        if path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]:
            raise RuntimeError(f"Release artifact changed: {path.name}")
    checksums = "".join(
        f"{entry['sha256']}  {entry['name']}\n"
        for entry in sorted(records, key=lambda entry: entry["name"])
    )
    if (directory / "SHA256SUMS.txt").read_text(encoding="utf-8") != checksums:
        raise RuntimeError("SHA256SUMS differs from the verified release collection")
    return final


def sign_release(directory: Path, private: Path, sequence: int, tag: str | None = None) -> dict:
    final = verified_collection(directory)
    app_version = final["version"]
    version(app_version)
    tag = release_tag(tag or f"v{app_version}", app_version)
    key = Ed25519PrivateKey.from_private_bytes(private.read_bytes())
    key_id, public = key_record(key)
    if trusted_keys().get(key_id) != public:
        raise RuntimeError("Signing key does not match the public key shipped in this checkout")
    stamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    artifacts = []
    seen = set()
    for entry in final["artifacts"]:
        name = filename(entry["name"])
        path = directory / name
        if name in seen or path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]:
            raise RuntimeError(f"Release file changed or repeats: {name}")
        seen.add(name)
        record = {
            "artifact_id": f"support-{len(artifacts)}",
            "filename": name,
            "bytes": entry["bytes"],
            "sha256": entry["sha256"],
            "urls": release_urls(tag, name),
        }
        for artifact_id, (platform, arch, kind, scope) in ARTIFACT_IDS.items():
            label = "Portable" if kind == "portable" else "Setup"
            deb = re.fullmatch(
                rf"djhx-bilix-gui_({re.escape(app_version)}-[1-9][0-9]*)_amd64.deb", name
            )
            if (kind == "deb" and deb) or (
                kind != "deb" and name == f"BiliX-GUI-{label}-{app_version}-windows-x64.exe"
            ):
                record.update(
                    artifact_id=artifact_id,
                    platform=platform,
                    arch=arch,
                    package_type=kind,
                    install_scope=scope,
                    package_version=deb.group(1) if kind == "deb" else app_version,
                    os_constraints={"glibc_min": "2.35"} if kind == "deb" else {"windows_min": 10},
                )
        artifacts.append(record)
    manifest = {
        "schema": 1,
        "product": "bilix",
        "channel": "stable",
        "version": app_version,
        "release_tag": tag,
        "published_at": stamp,
        "min_updater_schema": 1,
        "config_compatibility": "backup-before-migration",
        "artifacts": artifacts,
        "release_notes_url": f"https://github.com/Koril33/bilix/releases/tag/{tag}",
    }
    manifest_raw = encode_json(manifest)
    channel = {
        "schema": 1,
        "product": "bilix",
        "channel": "stable",
        "version": app_version,
        "release_tag": tag,
        "issued_at": stamp,
        "metadata_sequence": sequence,
        "manifest_bytes": len(manifest_raw),
        "manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
        "manifest_urls": release_urls(tag, "update-manifest.json"),
    }
    channel_raw = encode_json(channel)
    validate_channel(channel)
    for artifact_id in ARTIFACT_IDS:
        select_artifact(manifest, channel, artifact_id)  # All supported GUI formats must exist.
    blobs = {
        "stable.json": channel_raw,
        "stable.json.sig": sign_bytes(key, channel_raw),
        "update-manifest.json": manifest_raw,
        "update-manifest.json.sig": sign_bytes(key, manifest_raw),
    }
    for artifact_id in ARTIFACT_IDS:
        verify_bundle(blobs, artifact_id)
    for name, raw in blobs.items():
        if (directory / name).exists():
            raise RuntimeError(
                "Refusing to rewrite signed release metadata; use a fresh staging folder"
            )
    for name, raw in blobs.items():
        (directory / name).write_bytes(raw)
    shutil.copy2(ASSETS / "update-keys.json", directory / "update-keys.json")
    return channel


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("keygen")
    create.add_argument("--private-key", type=Path, required=True)
    create.add_argument("--backup-key", type=Path, required=True)
    create.add_argument("--public-keys", type=Path, default=ASSETS / "update-keys.json")
    sign = sub.add_parser("sign")
    sign.add_argument("--directory", type=Path, required=True)
    sign.add_argument("--private-key", type=Path, required=True)
    sign.add_argument("--sequence", type=int, required=True)
    sign.add_argument("--release-tag")
    args = parser.parse_args()
    if args.command == "keygen":
        keygen(args.private_key, args.backup_key, args.public_keys)
    else:
        channel = sign_release(args.directory, args.private_key, args.sequence, args.release_tag)
        print(
            f"Signed {channel['release_tag']} at metadata sequence {channel['metadata_sequence']}"
        )


if __name__ == "__main__":
    main()
