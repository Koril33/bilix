import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from djhx_bilix.updater import apply
from djhx_bilix.updater.client import PreparedUpdate
from djhx_bilix.updater.protocol import UpdateError, sha256, verify_bundle


def test_portable_replacement_preserves_renamed_original_and_previous_backup(signed_update):
    _, artifact = verify_bundle(signed_update["blobs"], "windows-x64-portable")
    prepared = PreparedUpdate(artifact, signed_update["directory"])
    target = signed_update["directory"] / "我的 程序.exe"
    target.write_bytes(b"old current")
    previous = target.with_name(target.name + ".previous.exe")
    previous.write_bytes(b"previous successful update")
    backup = apply.portable_replace(prepared, target, sha256(target), Path("transaction-id"))
    assert target.read_bytes() == signed_update["content"]
    assert backup.read_bytes() == b"old current"
    assert previous.read_bytes() == b"previous successful update"


def test_failed_second_move_restores_old_exe(signed_update, monkeypatch):
    _, artifact = verify_bundle(signed_update["blobs"], "windows-x64-portable")
    prepared = PreparedUpdate(artifact, signed_update["directory"])
    target = signed_update["directory"] / "current.exe"
    target.write_bytes(b"old")
    replace = os.replace

    def fail_new(source, destination):
        if ".new-" in Path(source).name:
            raise PermissionError("file in use")
        return replace(source, destination)

    monkeypatch.setattr(apply.os, "replace", fail_new)
    with pytest.raises(PermissionError):
        apply.portable_replace(prepared, target, sha256(target), Path("transaction-id"))
    assert target.read_bytes() == b"old"
    assert not list(target.parent.glob("*.new-*"))


def test_preferences_backup_excludes_token(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    for name in ("config.toml", "gui.ini", "token.txt"):
        (config / name).write_text(name)
    transaction = tmp_path / "transaction"
    transaction.mkdir()
    apply.backup_preferences(config, transaction)
    assert {p.name for p in (transaction / "config-backup").iterdir()} == {"config.toml", "gui.ini"}
    assert (config / "token.txt").read_text() == "token.txt"


def test_unlaunchable_new_executable_uses_portable_recovery_path(signed_update, monkeypatch):
    from djhx_bilix.updater.client import atomic_json
    from djhx_bilix.updater.protocol import read_json

    directory = signed_update["directory"]
    target = directory / "current.exe"
    target.write_bytes(b"old executable")
    transaction = directory / "transaction"
    transaction.mkdir()
    atomic_json(
        transaction / "request.json",
        {
            "schema": 1,
            "directory": str(directory),
            "artifact_id": "windows-x64-portable",
            "target": str(target),
            "version": "1.8.0",
            "old_sha256": sha256(target),
            "processes": [],
        },
    )
    monkeypatch.setattr(apply, "other_instances", lambda *args, **kwargs: [])
    monkeypatch.setattr(apply, "_message", lambda text: None)
    calls = []

    def start(arguments, **kwargs):
        calls.append(arguments)
        if "--updated" in arguments:
            raise OSError("not an executable")
        assert target.read_bytes() == b"old executable"
        return SimpleNamespace()

    monkeypatch.setattr(apply.subprocess, "Popen", start)
    assert apply.apply_update(transaction) == 1
    assert target.read_bytes() == b"old executable"
    assert len(calls) == 2  # New launch failed, then the restored old app launches once.
    assert not list(directory.glob("current.exe.previous-*"))
    assert read_json((transaction / "result.json").read_bytes())["installed"] is False


def _root_fixture(signed_update, monkeypatch):
    executable = signed_update["directory"] / "root-owned-helper"
    monkeypatch.setattr(apply.sys, "platform", "linux")
    monkeypatch.setattr(apply.sys, "argv", [str(executable)])
    monkeypatch.setattr(apply.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(apply.os, "O_NOFOLLOW", 0, raising=False)
    monkeypatch.setattr(apply.os, "O_NONBLOCK", 0, raising=False)
    monkeypatch.setattr(apply, "LINUX_EXECUTABLE", executable)
    monkeypatch.setattr(apply, "ROOT_STAGING", signed_update["directory"] / "root-staging")
    # Model a root-owned package/cache; Windows and unprivileged CI cannot create UID 0 files.
    monkeypatch.setattr(apply, "require_root_owned", lambda *args, **kwargs: None)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[0] == "/usr/bin/dpkg-deb":
            return SimpleNamespace(returncode=0, stdout="djhx-bilix-gui 1.8.0-1 amd64")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(apply.subprocess, "run", run)
    monkeypatch.setattr(
        apply,
        "installed_deb_version",
        lambda: "1.8.0-1" if any(c[0] == "/usr/bin/apt-get" for c in calls) else "1.7.5-1",
    )
    return calls


def test_root_installs_only_verified_copy_in_root_staging(signed_update, monkeypatch):
    calls = _root_fixture(signed_update, monkeypatch)
    assert apply.root_install_deb(signed_update["directory"]) == 0
    install = next(c for c in calls if c[0] == "/usr/bin/apt-get")
    assert "--no-remove" in install and "install" in install
    assert apply.ROOT_STAGING in Path(install[-1]).parents
    assert not apply.ROOT_STAGING.exists() or not list(apply.ROOT_STAGING.glob("install-*"))


def test_root_rejects_tampered_deb_before_apt(signed_update, monkeypatch):
    calls = _root_fixture(signed_update, monkeypatch)
    _, artifact = verify_bundle(signed_update["blobs"], "linux-amd64-deb")
    (signed_update["directory"] / artifact.filename).write_bytes(b"x" * artifact.size)
    with pytest.raises(UpdateError, match="SHA256"):
        apply.root_install_deb(signed_update["directory"])
    assert not any(c[0] == "/usr/bin/apt-get" for c in calls)


def test_internal_dispatch_does_not_import_qt(monkeypatch):
    from djhx_bilix import gui

    monkeypatch.setattr(apply, "dispatch", lambda args: 12)
    modules = set(sys.modules)
    assert gui.main(["--apply-update", "unused"]) == 12
    assert not any(m.startswith("PySide6") for m in set(sys.modules) - modules)


def test_aborted_handoff_stops_wait_without_replacing_or_restarting(tmp_path):
    from djhx_bilix.updater.processes import wait_for_exit

    marker = tmp_path / "abort.json"
    marker.write_text("{}")
    with pytest.raises(UpdateError, match="交接已取消"):
        wait_for_exit([], abort=marker)


def test_inno_reboot_required_does_not_restart_pending_install(signed_update, monkeypatch):
    from djhx_bilix.updater.client import atomic_json
    from djhx_bilix.updater.protocol import read_json

    directory = signed_update["directory"]
    target = directory / "installation/runtime/BiliX-GUI.exe"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"current")
    transaction = directory / "transaction"
    transaction.mkdir()
    atomic_json(
        transaction / "request.json",
        {
            "schema": 1,
            "directory": str(directory),
            "artifact_id": "windows-x64-installer",
            "target": str(target),
            "version": "1.8.0",
            "processes": [],
        },
    )
    monkeypatch.setattr(apply, "installer_location", lambda: target.parent.parent)
    monkeypatch.setattr(apply, "other_instances", lambda *args, **kwargs: [])
    monkeypatch.setattr(apply, "_message", lambda text: None)
    monkeypatch.setattr(
        apply.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=3010)
    )

    def no_restart(*args, **kwargs):
        pytest.fail("An installer pending a system reboot must not restart the application")

    monkeypatch.setattr(apply.subprocess, "Popen", no_restart)
    assert apply.apply_update(transaction) == 1
    assert read_json((transaction / "result.json").read_bytes())["installed"] is True


@pytest.mark.parametrize("uid,mode", [(1000, 0o755), (0, 0o777)])
def test_privileged_staging_rejects_wrong_owner_or_writable_directory(uid, mode):
    path = SimpleNamespace(lstat=lambda: SimpleNamespace(st_uid=uid, st_mode=stat.S_IFDIR | mode))
    with pytest.raises(UpdateError, match="权限"):
        apply.require_root_owned(path, directory=True)
