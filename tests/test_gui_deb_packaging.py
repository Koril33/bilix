"""Checks for Debian dependency metadata without pretending to build a Linux binary."""

import importlib
from pathlib import Path
from types import SimpleNamespace


def test_private_qt_libraries_do_not_become_system_dependencies(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    packaging = importlib.import_module("package_gui_deb")
    source_root = tmp_path / "source"
    (source_root / "debian").mkdir(parents=True)
    runtime = source_root / "debian" / packaging.PACKAGE / "usr" / "lib" / packaging.PACKAGE
    runtime.mkdir(parents=True)
    (runtime / "bilix-gui").write_bytes(b"\x7fELF")
    (runtime / "libQt6Core.so.6").write_bytes(b"\x7fELF")
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[0] == "readelf":
            return SimpleNamespace(
                returncode=0,
                stdout="0x000000000000000e (SONAME) Library soname: [libQt6Core.so.6]\n",
                stderr="",
            )
        assert command[0] == "dpkg-shlibdeps"
        return SimpleNamespace(
            returncode=0,
            stdout=f"shlibs:Depends={packaging.PACKAGE} (>= 1.6.0), libc6 (>= 2.35)\n",
            stderr="",
        )

    monkeypatch.setattr(packaging.subprocess, "run", run)
    assert packaging.shared_library_dependencies(source_root, runtime) == ["libc6 (>= 2.35)"]
    assert (source_root / "debian" / "shlibs.local").read_text(encoding="utf-8") == (
        f"libQt6Core 6 {packaging.PACKAGE} (>= {packaging.deb_version()})\n"
    )
    assert f"-x{packaging.PACKAGE}" in calls[-1]
