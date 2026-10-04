"""Platform wheel licensing differences must remain explicit in GUI bundles."""

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_linux_qt_wheel_without_notice_keeps_license_metadata(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    release = importlib.import_module("gui_release")
    interpreter = tmp_path / "interpreter"
    interpreter.mkdir()
    (interpreter / "LICENSE").write_text("Python license fixture", encoding="utf-8")
    root = tmp_path / "repo"
    root.mkdir()
    (root / "LICENSE").write_text("GPL license fixture", encoding="utf-8")
    monkeypatch.setattr(release, "ROOT", root)
    monkeypatch.setattr(release.sys, "base_prefix", str(interpreter))
    monkeypatch.setattr(release, "RUNTIME_PACKAGES", ("PySide6-Essentials",))
    qt = SimpleNamespace(version="6.11.2", metadata={"License": "LGPL-3.0-only OR GPL-3.0-only"})
    nuitka = SimpleNamespace(version="4.2.2")
    notice = {name: root / name for name in ("LICENSE-RUNTIME.txt", "NOTICE.txt")}
    for path in notice.values():
        path.write_text("Nuitka fixture", encoding="utf-8")
    nuitka.locate_file = lambda path: notice[path.name]
    monkeypatch.setattr(
        release.importlib.metadata,
        "distribution",
        lambda name: qt if name == "PySide6-Essentials" else nuitka,
    )
    monkeypatch.setattr(
        release,
        "_license_paths",
        lambda distribution: [] if distribution is qt else [Path(name) for name in notice],
    )

    linux = tmp_path / "linux"
    release.collect_licenses(linux, linux=True)
    qt_notice = (linux / "pyside6-essentials" / "WHEEL-LICENSE.txt").read_text(encoding="utf-8")
    assert "GPL-3.0-only" in qt_notice
    assert "no separate license file" in qt_notice
    assert (linux / "BiliX-GPL-3.0.txt").is_file()

    with pytest.raises(RuntimeError, match="No installed license files"):
        release.collect_licenses(tmp_path / "windows", linux=False)
