"""The two platform builds must coexist and produce a verified release list."""

import importlib
import json
import tarfile
import zipfile
from pathlib import Path

import pytest


def _modules(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("gui_release"), importlib.import_module("assemble_gui_release")


def test_assemble_keeps_both_platforms_and_detects_tampering(monkeypatch, tmp_path):
    release, assemble = _modules(monkeypatch)
    expected = assemble.expected_names()
    for platform, names in expected.items():
        paths = []
        for name in names:
            path = tmp_path / name
            path.write_bytes(f"{platform}:{name}".encode())
            paths.append(path)
        release.artifact_manifest(
            paths,
            tmp_path / f"release-manifest-{platform}.json",
            checksums_destination=tmp_path / f"SHA256SUMS-{platform}.txt",
        )

    paths = assemble.assemble(tmp_path)
    combined = json.loads((tmp_path / "release-manifest.json").read_text(encoding="utf-8"))
    assert {item["name"] for item in combined["artifacts"]} == set.union(*expected.values())
    assert len(paths) == 5
    assert len((tmp_path / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()) == 5

    paths[0].write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="changed after packaging|wrong-size"):
        assemble.assemble(tmp_path)


def test_source_bundle_excludes_vagrant_state_and_rejects_private_keys(monkeypatch, tmp_path):
    release, _ = _modules(monkeypatch)
    root = tmp_path / "repo"
    root.mkdir()
    entries = []
    for name in release.SOURCE_ROOT_FILES:
        path = root / name
        path.write_text("fixture", encoding="utf-8")
        entries.append(name)
    application = root / "src" / "djhx_bilix" / "__init__.py"
    application.parent.mkdir(parents=True)
    application.write_text("# application fixture\n", encoding="utf-8")
    entries.append("src/djhx_bilix/__init__.py")
    local_key = root / "tests" / "vm" / ".vagrant" / "keys" / "vagrant.key.rsa"
    local_key.parent.mkdir(parents=True)
    local_key.write_bytes(b"fixture")
    manifest = tmp_path / "sources.list"
    manifest.write_bytes(b"\0".join(item.encode() for item in entries) + b"\0")
    monkeypatch.setattr(release, "ROOT", root)
    monkeypatch.setenv("BILIX_SOURCE_FILE_LIST", str(manifest))

    destination = tmp_path / "safe"
    release.copy_sources(destination, linux=True)
    assert (destination / "src" / "djhx_bilix" / "__init__.py").is_file()
    assert not (destination / "tests").exists()

    manifest.write_bytes(manifest.read_bytes() + b"tests/vm/.vagrant/keys/vagrant.key.rsa\0")
    with pytest.raises(RuntimeError, match="Unsafe release source path"):
        release.copy_sources(tmp_path / "rejected", linux=True)


def test_release_archive_scan_rejects_vm_state(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    assemble = importlib.import_module("assemble_release")
    archive_path = tmp_path / "source.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("SOURCES/tests/vm/.vagrant/keys/fixture.rsa", b"fixture")
    with pytest.raises(RuntimeError, match="unsafe path"):
        assemble._verify_public_archive(archive_path)

    source_path = tmp_path / "source.tar.gz"
    fixture = tmp_path / "fixture"
    fixture.write_bytes(b"fixture")
    with tarfile.open(source_path, "w:gz") as archive:
        archive.add(fixture, arcname="project/tests/vm/.vagrant/state")
    with pytest.raises(RuntimeError, match="unsafe path"):
        assemble._verify_public_archive(source_path)
