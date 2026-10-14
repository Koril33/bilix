import base64
import hashlib

import pytest

from djhx_bilix.updater.protocol import ARTIFACT_IDS, encode_json, release_urls


@pytest.fixture
def signed_update(tmp_path, monkeypatch):
    crypto = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519")
    serialization = pytest.importorskip("cryptography.hazmat.primitives.serialization")
    from djhx_bilix.updater import protocol

    key = crypto.Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    keys = {"test": base64.b64encode(public).decode()}
    monkeypatch.setattr(protocol, "trusted_keys", lambda: keys)
    content = b"verified test update bytes"
    app_version = "1.8.1"
    tag = "v1.8.1"
    entries = []
    for artifact_id, (platform, arch, kind, scope) in ARTIFACT_IDS.items():
        label = "Portable" if kind == "portable" else "Setup"
        name = (
            f"djhx-bilix-gui_{app_version}-1_amd64.deb"
            if kind == "deb"
            else f"BiliX-GUI-{label}-{app_version}-windows-x64.exe"
        )
        entry = dict(
            artifact_id=artifact_id,
            platform=platform,
            arch=arch,
            package_type=kind,
            install_scope=scope,
            filename=name,
            bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            urls=release_urls(tag, name),
            package_version=app_version + "-1" if kind == "deb" else app_version,
            os_constraints={"glibc_min": "2.35"} if kind == "deb" else {"windows_min": 10},
        )
        entries.append(entry)
        (tmp_path / name).write_bytes(content)
    manifest = dict(
        schema=1,
        product="bilix",
        channel="stable",
        version=app_version,
        release_tag=tag,
        min_updater_schema=1,
        config_compatibility="backup-before-migration",
        published_at="2026-10-11T00:00:00Z",
        release_notes_url="https://github.com/Koril33/bilix/releases/tag/v1.8.1",
        artifacts=entries,
    )

    def sign(raw):
        return encode_json(
            dict(
                format=1,
                algorithm="Ed25519",
                key_id="test",
                signature=base64.b64encode(key.sign(raw)).decode(),
            )
        )

    def bundle(manifest=manifest, sequence=10):
        raw_manifest = encode_json(manifest)
        channel = dict(
            schema=1,
            product="bilix",
            channel="stable",
            metadata_sequence=sequence,
            issued_at="2026-10-11T00:00:00Z",
            version=manifest["version"],
            release_tag=manifest["release_tag"],
            manifest_sha256=hashlib.sha256(raw_manifest).hexdigest(),
            manifest_bytes=len(raw_manifest),
            manifest_urls=release_urls(manifest["release_tag"], "update-manifest.json"),
        )
        raw = encode_json(channel)
        return {
            "stable.json": raw,
            "stable.json.sig": sign(raw),
            "update-manifest.json": raw_manifest,
            "update-manifest.json.sig": sign(raw_manifest),
        }

    blobs = bundle()
    for name, raw in blobs.items():
        (tmp_path / name).write_bytes(raw)
    return dict(
        directory=tmp_path,
        blobs=blobs,
        keys=keys,
        content=content,
        manifest=manifest,
        bundle=bundle,
        sign=sign,
        key=key,
    )
