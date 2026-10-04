"""Release assembly checks the real Debian container, not just its filename."""

import importlib
import tarfile
from io import BytesIO
from pathlib import Path

import pytest


def _assembler(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("assemble_release")


def _tar(entries: dict[str, bytes | None], *, non_executable=()) -> bytes:
    output = BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, content in entries.items():
            member = tarfile.TarInfo(name)
            if name in ("usr/bin/bilix-gui", "usr/lib/djhx-bilix-gui/bilix-gui"):
                member.mode = 0o644 if name in non_executable else 0o755
            if content is None:
                member.type = tarfile.SYMTYPE
                member.linkname = "/etc/passwd"
                archive.addfile(member)
            else:
                member.size = len(content)
                archive.addfile(member, BytesIO(content))
    return output.getvalue()


def _ar(members: dict[str, bytes]) -> bytes:
    output = bytearray(b"!<arch>\n")
    for name, body in members.items():
        header = (f"{name + '/':<16}{0:<12}{0:<6}{0:<6}{0o100644:<8}{len(body):<10}`\n").encode(
            "ascii"
        )
        assert len(header) == 60
        output.extend(header)
        output.extend(body)
        if len(body) % 2:
            output.extend(b"\n")
    return bytes(output)


def _deb(assembler, tmp_path, *, fields=None, data=None, removed=(), non_executable=()):
    control_fields = {
        "Package": "djhx-bilix-gui",
        "Version": assembler.deb_version(),
        "Architecture": "amd64",
        "Maintainer": "BiliX Tester <tester@example.org>",
    }
    control_fields.update(fields or {})
    control = "".join(f"{key}: {value}\n" for key, value in control_fields.items()).encode()
    contents = {name: b"fixture" for name in assembler.DEB_REQUIRED_FILES}
    contents["usr/lib/djhx-bilix-gui/certifi/cacert.pem"] = b"public CA certificates"
    contents["usr/share/applications/djhx-bilix-gui.desktop"] = (
        b"[Desktop Entry]\nType=Application\nExec=bilix-gui\nIcon=djhx-bilix-gui\n"
    )
    if data:
        contents.update(data)
    for name in removed:
        contents.pop(name)
    path = tmp_path / "test.deb"
    path.write_bytes(
        _ar(
            {
                "debian-binary": b"2.0\n",
                "control.tar.gz": _tar({"./control": control}),
                "data.tar.gz": _tar(contents, non_executable=non_executable),
            }
        )
    )
    return path


def test_debian_archive_verifies_control_and_installed_files(monkeypatch, tmp_path):
    assembler = _assembler(monkeypatch)
    assembler._verify_public_archive(_deb(assembler, tmp_path))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("Package", "other-project"),
        ("Version", "1.6.0.dev0-1"),
        ("Architecture", "arm64"),
        ("Maintainer", "invalid address"),
    ],
)
def test_debian_archive_rejects_wrong_control_fields(monkeypatch, tmp_path, field, value):
    assembler = _assembler(monkeypatch)
    with pytest.raises(RuntimeError, match=f"{field}|Maintainer"):
        assembler._verify_public_archive(_deb(assembler, tmp_path, fields={field: value}))


@pytest.mark.parametrize(
    "unsafe",
    [
        "usr/share/doc/djhx-bilix-gui/.vagrant/keys/vagrant.key.rsa",
        "usr/lib/djhx-bilix-gui/private.pem",
        "../outside-file",
        "C:/outside-file",
    ],
)
def test_debian_archive_rejects_unsafe_paths(monkeypatch, tmp_path, unsafe):
    assembler = _assembler(monkeypatch)
    with pytest.raises(RuntimeError, match="unsafe path"):
        assembler._verify_public_archive(_deb(assembler, tmp_path, data={unsafe: b"bad"}))


def test_debian_archive_rejects_symlinks_and_missing_licenses(monkeypatch, tmp_path):
    assembler = _assembler(monkeypatch)
    with pytest.raises(RuntimeError, match="link or special file"):
        assembler._verify_public_archive(
            _deb(assembler, tmp_path, data={"usr/lib/djhx-bilix-gui/linked": None})
        )
    missing = "usr/share/doc/djhx-bilix-gui/LICENSE"
    with pytest.raises(RuntimeError, match="lacks required files"):
        assembler._verify_public_archive(_deb(assembler, tmp_path, removed=(missing,)))


def test_debian_archive_rejects_corrupt_ar_header(monkeypatch, tmp_path):
    assembler = _assembler(monkeypatch)
    path = _deb(assembler, tmp_path)
    path.write_bytes(path.read_bytes().replace(b"!<arch>\n", b"!broken\n", 1))
    with pytest.raises(RuntimeError, match="invalid ar header"):
        assembler._verify_public_archive(path)


def test_debian_archive_rejects_broken_desktop_and_nonexecutable_launcher(monkeypatch, tmp_path):
    assembler = _assembler(monkeypatch)
    desktop = "usr/share/applications/djhx-bilix-gui.desktop"
    with pytest.raises(RuntimeError, match="desktop entry lacks Exec"):
        assembler._verify_public_archive(
            _deb(assembler, tmp_path, data={desktop: b"[Desktop Entry]\nType=Application\n"})
        )
    with pytest.raises(RuntimeError, match="execute permission"):
        assembler._verify_public_archive(
            _deb(assembler, tmp_path, non_executable=("usr/bin/bilix-gui",))
        )
