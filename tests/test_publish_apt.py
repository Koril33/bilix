"""Publication integrity and ordering, without SSH or private credentials."""

import base64
import gzip
import hashlib
import importlib
import io
import json
import os
import re
import stat
import subprocess
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def publisher(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("publish_apt")


@pytest.fixture
def public_tree(tmp_path, publisher, monkeypatch):
    root = tmp_path / "public"
    pool = "pool/main/d/djhx-bilix-gui/djhx-bilix-gui_1.7.8-1_amd64.deb"
    content = b"public package fixture"
    package = (
        "Package: djhx-bilix-gui\nArchitecture: amd64\nVersion: 1.7.8-1\n"
        f"Filename: {pool}\nSize: {len(content)}\nSHA256: {hashlib.sha256(content).hexdigest()}\n"
    ).encode()
    indexes = {"main/binary-amd64/Packages": package}
    release = (
        "Suite: stable\nCodename: stable\nArchitectures: amd64\n"
        "Components: main\nAcquire-By-Hash: yes\n"
    )
    files = {pool: content, publisher.KEY_PATH: b"PUBLIC KEY FIXTURE"}
    for field, algorithm in publisher.ALGORITHMS.items():
        release += field + ":\n"
        for name, data in indexes.items():
            checksum = hashlib.new(algorithm, data).hexdigest()
            release += f" {checksum} {len(data)} {name}\n"
            files[f"dists/stable/main/binary-amd64/by-hash/{field}/{checksum}"] = data
    files.update({"dists/stable/" + name: data for name, data in indexes.items()})
    files[publisher.RELEASE_PATH] = release.encode()
    files[publisher.RELEASE_PATH + ".gpg"] = b"DETACHED SIGNATURE FIXTURE"
    files["dists/stable/InRelease"] = b"CLEAR SIGNATURE FIXTURE"
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    monkeypatch.setattr(
        publisher, "verify_signatures", lambda directory: publisher.TRUSTED_FINGERPRINT
    )
    return root


def archive_for(stage, directory, records):
    with tarfile.open(stage / "upload.tar", "w") as archive:
        for item in records:
            data = (directory / item["path"]).read_bytes()
            entry = tarfile.TarInfo(item["path"])
            entry.size = len(data)
            archive.addfile(entry, io.BytesIO(data))


def transaction(publisher, public_tree, tmp_path):
    root = tmp_path / "remote"
    root.mkdir()
    report = publisher.verify_public(public_tree)
    request = {"action": "begin", "token": "a" * 32, "files": report["files"]}
    publisher.remote_operation(request, str(root), check_identity=False)
    archive_for(root / (".staging-" + request["token"]), public_tree, report["files"])
    request["action"] = "commit"
    return root, request


def test_verifies_signed_indexes_packages_and_real_by_hash(publisher, public_tree):
    report = publisher.verify_public(public_tree)
    assert report["fingerprint"] == publisher.TRUSTED_FINGERPRINT
    assert len(report["files"]) == 10
    package = next(public_tree.glob("pool/**/*.deb"))
    package.write_bytes(b"tampered fixture")
    with pytest.raises(ValueError, match="differs from Packages"):
        publisher.verify_public(public_tree)


def test_missing_signed_index_rejected(publisher, public_tree):
    (public_tree / "dists/stable/main/binary-amd64/Packages").unlink()
    with pytest.raises(ValueError, match="Missing.*signed APT index"):
        publisher.verify_public(public_tree)


def test_bad_by_hash_rejected_and_aptly_alias_excluded(publisher, public_tree):
    parent = public_tree / "dists/stable/main/binary-amd64/by-hash/SHA256"
    (parent / "Packages.old").write_bytes(b"old public alias")
    report = publisher.verify_public(public_tree)
    assert report["ignored_aliases"] == [
        "dists/stable/main/binary-amd64/by-hash/SHA256/Packages.old"
    ]
    assert not any(item["path"].endswith("Packages.old") for item in report["files"])
    (parent / ("0" * 64)).write_bytes(b"wrong digest")
    with pytest.raises(ValueError, match="Incorrect content-addressed"):
        publisher.verify_public(public_tree)


@pytest.mark.parametrize(
    "value", ["../secret", "/pool/package", "pool\\package", "pool//file", "pool/./file"]
)
def test_rejects_unsafe_paths(publisher, value):
    with pytest.raises(ValueError, match="Unsafe APT path"):
        publisher.safe_path(value)


def test_rejects_unknown_public_file(publisher, public_tree):
    (public_tree / "unreviewed.txt").write_bytes(b"unexpected public content")
    with pytest.raises(ValueError, match="Unexpected APT public file"):
        publisher.verify_public(public_tree)


def test_signature_requires_existing_primary_fingerprint(publisher, tmp_path, monkeypatch):
    directory = tmp_path / "public"
    key = directory / publisher.KEY_PATH
    key.parent.mkdir(parents=True)
    key.write_bytes(b"PUBLIC KEY FIXTURE")
    monkeypatch.setattr(
        publisher, "_gpg", lambda arguments: b"pub:::::::::\nfpr:::::::::BADFINGERPRINT:\n"
    )
    # Call the implementation, not the public_tree fixture's signature substitute.
    with pytest.raises(ValueError, match="trusted fingerprint"):
        publisher.verify_signatures(directory)


def test_detached_and_clear_signed_release_must_agree(publisher, tmp_path, monkeypatch):
    directory = tmp_path / "public"
    for name, data in {
        publisher.KEY_PATH: b"PUBLIC KEY FIXTURE",
        publisher.RELEASE_PATH: b"Suite: stable\n",
        publisher.RELEASE_PATH + ".gpg": b"signature fixture",
        "dists/stable/InRelease": b"clear signature fixture",
    }.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def gpg(arguments):
        if "--show-keys" in arguments:
            return f"pub:::::::::\nfpr:::::::::{publisher.TRUSTED_FINGERPRINT}:\n".encode()
        if arguments[0] == "gpgv":
            if "--output" in arguments:
                Path(arguments[arguments.index("--output") + 1]).write_bytes(b"different Release\n")
            return (
                f"[GNUPG:] VALIDSIG {publisher.TRUSTED_FINGERPRINT} "
                "2026-10-13 1791849600 0 4 0 22 8 00\n"
            ).encode()
        return b""

    monkeypatch.setattr(publisher, "_gpg", gpg)
    with pytest.raises(ValueError, match="different metadata"):
        publisher.verify_signatures(directory)


def test_immutable_conflict_prevents_every_activation(publisher, public_tree, tmp_path):
    root, request = transaction(publisher, public_tree, tmp_path)
    pool = next(item for item in request["files"] if item["path"].startswith("pool/"))
    destination = root / pool["path"]
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"existing distinct package")
    with pytest.raises(RuntimeError, match="Refusing to change immutable"):
        publisher.remote_operation(request, str(root), check_identity=False)
    assert destination.read_bytes() == b"existing distinct package"
    assert not (root / publisher.RELEASE_PATH).exists()
    assert not (root / ".publish-lock").exists()


def test_activation_preserves_history_orders_final_group_and_retains_evidence(
    publisher, public_tree, tmp_path, monkeypatch
):
    root, request = transaction(publisher, public_tree, tmp_path)
    historical = root / "pool/old-package.deb"
    historical.parent.mkdir()
    historical.write_bytes(b"historical public package")
    activated = []
    original = publisher.os.replace

    def record(source, target):
        activated.append(Path(target).relative_to(root).as_posix())
        original(source, target)

    monkeypatch.setattr(publisher.os, "replace", record)
    result = publisher.remote_operation(request, str(root), check_identity=False)
    assert result["status"] == "published" and result["atomic_group"] is False
    assert activated[-3:] == [
        publisher.RELEASE_PATH + ".gpg",
        publisher.RELEASE_PATH,
        "dists/stable/InRelease",
    ]
    assert historical.read_bytes() == b"historical public package"
    stage = root / (".staging-" + request["token"])
    assert (stage / "upload.tar").is_file() and (stage / "manifest.json").is_file()
    assert json.loads((stage / "status.json").read_text())["status"] == "published"
    assert not (root / ".publish-lock").exists()


def test_upload_tampering_fails_before_indexes_change(publisher, public_tree, tmp_path):
    root, request = transaction(publisher, public_tree, tmp_path)
    package = next(public_tree.glob("pool/**/*.deb"))
    package.write_bytes(b"x" * package.stat().st_size)
    archive_for(root / (".staging-" + request["token"]), public_tree, request["files"])
    with pytest.raises(RuntimeError, match="bytes differ"):
        publisher.remote_operation(request, str(root), check_identity=False)
    assert not (root / publisher.RELEASE_PATH).exists()
    assert not (root / ".publish-lock").exists()
    assert (
        json.loads((root / (".staging-" + request["token"]) / "status.json").read_text())["status"]
        == "failed"
    )


def test_existing_key_cannot_change(publisher, public_tree, tmp_path):
    root = tmp_path / "remote"
    path = root / publisher.KEY_PATH
    path.parent.mkdir(parents=True)
    path.write_bytes(b"different existing public key")
    request = {"action": "check", "files": publisher.verify_public(public_tree)["files"]}
    with pytest.raises(RuntimeError, match="existing key"):
        publisher.remote_operation(request, str(root), check_identity=False)


def test_check_never_stages_uploads_or_reads_ssh_key(publisher, public_tree, tmp_path, monkeypatch):
    credential = tmp_path / "test-ssh-key"
    credential.write_text("FAKE_UNUSED_CREDENTIAL", encoding="utf-8")
    calls = []

    def run(arguments, **kwargs):
        calls.append(arguments)
        assert Path(arguments[0]).stem == "ssh"
        assert publisher.REMOTE_HOST in arguments
        assert json.loads(kwargs["input"])["action"] == "check"
        assert "\n" not in arguments[-1]
        encoded = re.search(r'b64decode\("([A-Za-z0-9+/=]+)"\)', arguments[-1])[1]
        decoded = base64.b64decode(encoded).decode("utf-8")
        assert "def remote_operation" in decoded
        compile(decoded, "uploaded-script", "exec")
        return subprocess.CompletedProcess(arguments, 0, b'{"status":"checked","account":"bilix"}')

    monkeypatch.setattr(publisher.subprocess, "run", run)
    original = Path.read_bytes

    def read_bytes(path):
        assert path != credential
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    assert publisher.publish(public_tree, credential, check=True)["status"] == "checked"
    assert len(calls) == 1


def test_read_only_remote_check_leaves_no_lock_or_stage(publisher, public_tree, tmp_path):
    root = tmp_path / "remote"
    root.mkdir()
    request = {"action": "check", "files": publisher.verify_public(public_tree)["files"]}
    assert (
        publisher.remote_operation(request, str(root), check_identity=False)["status"] == "checked"
    )
    assert list(root.iterdir()) == []


def signature_fixture(publisher, root, monkeypatch, *, status="", signer=None, primary=None):
    key = root / publisher.KEY_PATH
    key.parent.mkdir(parents=True)
    key.write_bytes(b"PUBLIC KEY FIXTURE")
    release = root / publisher.RELEASE_PATH
    release.parent.mkdir(parents=True)
    release.write_bytes(b"Suite: stable\n")
    primary = primary or publisher.TRUSTED_FINGERPRINT
    signer = signer or primary

    def gpg(arguments):
        if "--show-keys" in arguments:
            return f"pub:::::::::\nfpr:::::::::{primary}:\n".encode()
        if arguments[0] == "gpgv":
            if "--output" in arguments:
                Path(arguments[arguments.index("--output") + 1]).write_bytes(release.read_bytes())
            return (
                f"[GNUPG:] VALIDSIG {signer} 2026-10-13 1791849600 0 4 0 22 8 00 {primary}\n"
                + status
            ).encode()
        return b""

    monkeypatch.setattr(publisher, "_gpg", gpg)


@pytest.mark.parametrize("marker", ["KEYREVOKED", "BADSIG", "EXPKEYSIG", "REVKEYSIG"])
def test_rejects_invalid_gpg_status_even_with_validsig(publisher, tmp_path, monkeypatch, marker):
    signature_fixture(publisher, tmp_path / "public", monkeypatch, status=f"[GNUPG:] {marker}\n")
    with pytest.raises(ValueError, match="not valid"):
        publisher.verify_signatures(tmp_path / "public")


@pytest.mark.parametrize("subkey", [False, True])
def test_accepts_valid_primary_or_bound_subkey_signature(publisher, tmp_path, monkeypatch, subkey):
    signature_fixture(
        publisher,
        tmp_path / "public",
        monkeypatch,
        signer="A" * 40 if subkey else None,
    )
    assert publisher.verify_signatures(tmp_path / "public") == publisher.TRUSTED_FINGERPRINT


def test_requires_current_sha512_by_hash_too(publisher, public_tree):
    next((public_tree / "dists/stable/main/binary-amd64/by-hash/SHA512").iterdir()).unlink()
    with pytest.raises(ValueError, match="current by-hash"):
        publisher.verify_public(public_tree)


def test_symlink_input_is_rejected_without_following_it(publisher, public_tree, monkeypatch):
    original = Path.lstat
    suspect = public_tree / publisher.KEY_PATH

    def lstat(path, *args, **kwargs):
        if path == suspect:
            return SimpleNamespace(st_mode=stat.S_IFLNK)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", lstat)
    with pytest.raises(ValueError, match="symlinks"):
        publisher.verify_public(public_tree)


def test_verifies_fixed_snapshot_again_before_ssh(publisher, public_tree, tmp_path, monkeypatch):
    original = publisher.verify_public
    calls = []

    def verify(directory):
        result = original(directory)
        calls.append(directory)
        if len(calls) == 1:
            next(public_tree.glob("pool/**/*.deb")).write_bytes(b"changed during snapshot copy")
        return result

    monkeypatch.setattr(publisher, "verify_public", verify)
    monkeypatch.setattr(publisher.subprocess, "run", lambda *a, **k: pytest.fail("Reached network"))
    with pytest.raises(ValueError, match="differs from Packages"):
        publisher.publish(public_tree, tmp_path / "unused-key", check=True)
    assert len(calls) == 1  # Second validation raises before returning.


def test_begin_failure_cleans_only_its_new_lock(publisher, public_tree, tmp_path, monkeypatch):
    root = tmp_path / "remote"
    root.mkdir()
    original = Path.write_text

    def write(path, *args, **kwargs):
        if path.name == "owner.json":
            raise OSError("fixture write failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", write)
    request = {
        "action": "begin",
        "token": "a" * 32,
        "files": publisher.verify_public(public_tree)["files"],
    }
    with pytest.raises(OSError, match="write failure"):
        publisher.remote_operation(request, str(root), check_identity=False)
    assert list(root.iterdir()) == []


def test_second_publisher_cannot_take_or_remove_first_lock(publisher, public_tree, tmp_path):
    root, request = transaction(publisher, public_tree, tmp_path)
    owner = (root / ".publish-lock/owner.json").read_bytes()
    competitor = {**request, "action": "begin", "token": "b" * 32}
    with pytest.raises(FileExistsError):
        publisher.remote_operation(competitor, str(root), check_identity=False)
    assert (root / ".publish-lock/owner.json").read_bytes() == owner
    assert not (root / (".staging-" + competitor["token"])).exists()


def test_abort_releases_owned_lock_even_after_destination_conflict(
    publisher, public_tree, tmp_path
):
    root, request = transaction(publisher, public_tree, tmp_path)
    key = root / publisher.KEY_PATH
    key.parent.mkdir()
    key.write_bytes(b"conflicting existing public key")
    assert (
        publisher.remote_operation({**request, "action": "abort"}, str(root), check_identity=False)[
            "status"
        ]
        == "upload-failed"
    )
    assert not (root / ".publish-lock").exists()
    assert key.read_bytes() == b"conflicting existing public key"


@pytest.mark.parametrize("failure", ["Release.gpg", "Release", "InRelease"])
def test_partial_final_switch_reports_progress_and_same_candidate_can_recover(
    publisher, public_tree, tmp_path, monkeypatch, failure
):
    root, request = transaction(publisher, public_tree, tmp_path)
    replace = publisher.os.replace

    def fail(source, destination):
        if Path(destination).name == failure:
            raise OSError("fixture final switch failure")
        replace(source, destination)

    monkeypatch.setattr(publisher.os, "replace", fail)
    with pytest.raises(OSError, match="switch failure"):
        publisher.remote_operation(request, str(root), check_identity=False)
    stage = root / (".staging-" + request["token"])
    status = json.loads((stage / "status.json").read_text())
    assert status["status"] == "failed" and status["phase"] == "activating"
    assert "dists/stable/" + failure not in status["completed"]
    assert status["completed"] and status["recovery"]
    assert not (root / ".publish-lock").exists()
    monkeypatch.setattr(publisher.os, "replace", replace)
    retry = {**request, "action": "begin", "token": "c" * 32}
    publisher.remote_operation(retry, str(root), check_identity=False)
    archive_for(root / (".staging-" + retry["token"]), public_tree, retry["files"])
    assert (
        publisher.remote_operation({**retry, "action": "commit"}, str(root), check_identity=False)[
            "status"
        ]
        == "published"
    )
    assert (root / publisher.RELEASE_PATH).read_bytes() == (
        public_tree / publisher.RELEASE_PATH
    ).read_bytes()


def test_new_public_directories_override_restrictive_umask(
    publisher, public_tree, tmp_path, monkeypatch
):
    root, request = transaction(publisher, public_tree, tmp_path)
    original = Path.chmod
    explicit = []

    def chmod(path, mode, *args, **kwargs):
        if mode == 0o755:
            explicit.append(path)
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "chmod", chmod)
    previous = os.umask(0o077)
    try:
        publisher.remote_operation(request, str(root), check_identity=False)
    finally:
        os.umask(previous)
    assert root / "pool" in explicit and root / "dists" in explicit
    if os.name != "nt":
        assert stat.S_IMODE((root / "pool").stat().st_mode) == 0o755
    stage_files = root / (".staging-" + request["token"]) / "files"
    assert not list(stage_files.glob("pool/**/*.deb"))


def add_contents_indexes(publisher, directory, *, compressed_data=None, missing_plain=True):
    contents = b"usr/bin/bilix-gui main/djhx-bilix-gui\n"
    indexes = {
        "main/binary-amd64/Packages": (
            directory / "dists/stable/main/binary-amd64/Packages"
        ).read_bytes(),
        "Contents-amd64": contents,
        "Contents-amd64.gz": gzip.compress(compressed_data or contents),
        "main/Contents-amd64": contents,
        "main/Contents-amd64.gz": gzip.compress(compressed_data or contents),
    }
    release = (
        "Suite: stable\nCodename: stable\nArchitectures: amd64\n"
        "Components: main\nAcquire-By-Hash: yes\n"
    )
    for field, algorithm in publisher.ALGORITHMS.items():
        release += field + ":\n"
        for name, data in indexes.items():
            checksum = hashlib.new(algorithm, data).hexdigest()
            release += f" {checksum} {len(data)} {name}\n"
            if missing_plain and name.endswith("Contents-amd64"):
                continue
            index = directory / "dists/stable" / name
            index.parent.mkdir(parents=True, exist_ok=True)
            index.write_bytes(data)
            by_hash = index.parent / "by-hash" / field / checksum
            by_hash.parent.mkdir(parents=True, exist_ok=True)
            by_hash.write_bytes(data)
    (directory / publisher.RELEASE_PATH).write_bytes(release.encode())


def test_aptly_gzip_only_contents_authenticates_logical_uncompressed_digest(publisher, public_tree):
    add_contents_indexes(publisher, public_tree)
    report = publisher.verify_public(public_tree)
    assert report["logical_indexes"] == [
        "dists/stable/Contents-amd64",
        "dists/stable/main/Contents-amd64",
    ]
    assert not any(item["path"].endswith("Contents-amd64") for item in report["files"])


def test_bad_expanded_contents_digest_cannot_hide_behind_valid_gzip_hash(publisher, public_tree):
    add_contents_indexes(publisher, public_tree, compressed_data=b"changed but signed gzip bytes")
    with pytest.raises(ValueError, match="Signed APT index differs"):
        publisher.verify_public(public_tree)


def test_missing_gzip_delivery_is_still_an_error(publisher, public_tree):
    add_contents_indexes(publisher, public_tree)
    (public_tree / "dists/stable/Contents-amd64.gz").unlink()
    with pytest.raises(ValueError, match="Missing.*signed APT index"):
        publisher.verify_public(public_tree)


@pytest.mark.parametrize("directory_mode", [False, True])
def test_check_rejects_existing_public_permission_drift(
    publisher, public_tree, tmp_path, monkeypatch, directory_mode
):
    root = tmp_path / "remote"
    root.mkdir()
    key = root / publisher.KEY_PATH
    key.parent.mkdir()
    key.write_bytes((public_tree / publisher.KEY_PATH).read_bytes())
    suspect = key.parent if directory_mode else key
    original = Path.stat

    def changed_mode(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == suspect:
            return SimpleNamespace(
                st_mode=(stat.S_IFDIR | 0o700) if directory_mode else (stat.S_IFREG | 0o600),
                st_size=info.st_size,
            )
        return info

    monkeypatch.setattr(Path, "stat", changed_mode)
    request = {"action": "check", "files": publisher.verify_public(public_tree)["files"]}
    with pytest.raises(RuntimeError, match="not publicly"):
        publisher.remote_operation(request, str(root), check_identity=False)
    assert not (root / ".publish-lock").exists()


def test_ssh_failure_does_not_dump_encoded_server_script(
    publisher, public_tree, tmp_path, monkeypatch
):
    credential = tmp_path / "test-ssh-key"
    credential.write_text("FAKE_UNUSED_CREDENTIAL", encoding="utf-8")

    def run(arguments, **kwargs):
        return subprocess.CompletedProcess(arguments, 2, b"", b"fixture transport failure")

    monkeypatch.setattr(publisher.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="fixture transport failure") as failure:
        publisher.publish(public_tree, credential, check=True)
    assert "b64decode" not in str(failure.value)
    assert "def remote_operation" not in str(failure.value)


def test_scp_and_abort_disconnect_reports_owned_lock_recovery(
    publisher, public_tree, tmp_path, monkeypatch
):
    credential = tmp_path / "test-ssh-key"
    credential.write_text("FAKE_UNUSED_CREDENTIAL", encoding="utf-8")

    def run(arguments, **kwargs):
        if Path(arguments[0]).stem == "scp":
            raise OSError("fixture upload disconnect")
        action = json.loads(kwargs["input"])["action"]
        if action == "begin":
            return subprocess.CompletedProcess(arguments, 0, b'{"status":"staged"}')
        assert action == "abort"
        return subprocess.CompletedProcess(arguments, 2, b"", b"fixture SSH disconnect")

    monkeypatch.setattr(publisher.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="lock release could not be confirmed") as failure:
        publisher.publish(public_tree, credential)
    assert "owner token" in str(failure.value)
    assert ".publish-lock/owner.json" in str(failure.value)
    assert "confirm no active publisher" in str(failure.value)


def test_prefers_native_windows_openssh_over_git_path(publisher, tmp_path, monkeypatch):
    native = tmp_path / "Windows/System32/OpenSSH"
    native.mkdir(parents=True)
    for name in ("ssh.exe", "scp.exe"):
        (native / name).write_bytes(b"NATIVE_TOOL_FIXTURE")
    monkeypatch.setenv("PATH", str(tmp_path / "Git/usr/bin"))
    assert publisher.ssh_tools(system="nt", system_root=tmp_path / "Windows") == (
        str(native / "ssh.exe"),
        str(native / "scp.exe"),
    )


def test_ssh_tool_fallback_on_other_os_or_missing_native_binary(publisher, tmp_path):
    assert publisher.ssh_tools(system="posix") == ("ssh", "scp")
    assert publisher.ssh_tools(system="nt", system_root=tmp_path) == ("ssh", "scp")
    native = tmp_path / "System32/OpenSSH"
    native.mkdir(parents=True)
    (native / "ssh.exe").write_bytes(b"NATIVE_TOOL_FIXTURE")
    assert publisher.ssh_tools(system="nt", system_root=tmp_path) == (
        str(native / "ssh.exe"),
        "scp",
    )
