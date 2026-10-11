import importlib
from pathlib import Path

import pytest

from djhx_bilix.updater.protocol import encode_json, sha256, verify_bundle


def release_collection(signed_update):
    directory = signed_update["directory"] / "release"
    directory.mkdir()
    records = []
    names = [entry["filename"] for entry in signed_update["manifest"]["artifacts"]]
    names += [
        "BiliX-GUI-licenses-and-source-1.8.0-windows-x64.zip",
        "djhx-bilix-gui_1.8.0_source.tar.gz",
        "djhx_bilix-1.8.0-py3-none-any.whl",
        "djhx_bilix-1.8.0.tar.gz",
        "bilix-1.8.0-windows-x64.zip",
    ]
    for name in names:
        path = directory / name
        path.write_bytes(signed_update["content"])
        records.append(dict(name=name, bytes=path.stat().st_size, sha256=sha256(path)))
    (directory / "release-manifest.json").write_bytes(
        encode_json(dict(version="1.8.0", artifacts=records))
    )
    (directory / "SHA256SUMS.txt").write_text(
        "".join(f"{r['sha256']}  {r['name']}\n" for r in sorted(records, key=lambda r: r["name"])),
        encoding="utf-8",
    )
    return directory


def test_sign_final_collection_and_reject_rewrite(signed_update, monkeypatch):
    serialization = pytest.importorskip("cryptography.hazmat.primitives.serialization")
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    signing = importlib.import_module("update_release")
    key_id, public = signing.key_record(signed_update["key"])
    signed_update["keys"].clear()
    signed_update["keys"][key_id] = public
    private = signed_update["directory"] / "ephemeral.key"
    private.write_bytes(
        signed_update["key"].private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
    )
    directory = release_collection(signed_update)
    public_root = signed_update["directory"] / "public-keys"
    public_root.mkdir()
    (public_root / "update-keys.json").write_bytes(
        encode_json({"format": 1, "keys": signed_update["keys"]})
    )
    monkeypatch.setattr(signing, "ASSETS", public_root)
    channel = signing.sign_release(directory, private, 123)
    assert channel["metadata_sequence"] == 123
    blobs = {
        name: (directory / name).read_bytes()
        for name in (
            "stable.json",
            "stable.json.sig",
            "update-manifest.json",
            "update-manifest.json.sig",
        )
    }
    _, artifact = verify_bundle(blobs, "linux-amd64-deb")
    artifact.verify_file(directory / artifact.filename)
    with pytest.raises(RuntimeError, match="rewrite"):
        signing.sign_release(directory, private, 124)


def test_changed_materials_rejected_before_signing(signed_update, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    signing = importlib.import_module("update_release")
    directory = release_collection(signed_update)
    (directory / "djhx_bilix-1.8.0.tar.gz").write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="changed"):
        signing.sign_release(directory, Path("private-key-not-needed"), 123)


def test_publisher_rejects_bad_signature_before_network(signed_update, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    publishing = importlib.import_module("publish_update")
    from djhx_bilix.updater.protocol import UpdateError

    (signed_update["directory"] / "stable.json").write_bytes(b'{"tampered": true}')

    def no_network(*args, **kwargs):
        pytest.fail("Unverified metadata reached SSH")

    monkeypatch.setattr(publishing.subprocess, "run", no_network)
    with pytest.raises(UpdateError, match="签名"):
        publishing.publish(signed_update["directory"], Path("unused-ssh-key"))
