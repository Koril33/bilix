"""CLI/GUI builders must reject mixed checkout and installed release identities."""

import importlib
from pathlib import Path

import pytest


@pytest.fixture
def build_identity(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    release = importlib.import_module("gui_release")
    initializer = tmp_path / "src" / "djhx_bilix" / "__init__.py"
    initializer.parent.mkdir(parents=True)
    initializer.write_text(f'__version__ = "{release.__version__}"\n', encoding="utf-8")
    monkeypatch.setattr(release, "ROOT", tmp_path)
    monkeypatch.setattr(release.djhx_bilix, "__file__", str(initializer))
    monkeypatch.setattr(release.importlib.metadata, "version", lambda _name: release.__version__)
    return release, initializer


def test_gui_build_accepts_current_editable_source_and_metadata(build_identity):
    release, _ = build_identity
    assert release.require_version_identity() == {
        "source": release.__version__,
        "imported": release.__version__,
        "installed": release.__version__,
    }


def test_gui_build_rejects_old_installed_metadata(build_identity, monkeypatch):
    release, _ = build_identity
    monkeypatch.setattr(release.importlib.metadata, "version", lambda _name: "1.3.2")
    with pytest.raises(RuntimeError, match="metadata 1.3.2 differ"):
        release.require_version_identity()


def test_gui_build_rejects_old_imported_package(build_identity, monkeypatch):
    release, _ = build_identity
    current = release.__version__
    monkeypatch.setattr(release, "__version__", "1.7.0")
    monkeypatch.setattr(release.importlib.metadata, "version", lambda _name: current)
    with pytest.raises(RuntimeError, match="imported version 1.7.0"):
        release.require_version_identity()


def test_gui_build_rejects_changed_checkout_version(build_identity):
    release, initializer = build_identity
    initializer.write_text('__version__ = "1.7.0"\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="checkout version 1.7.0"):
        release.require_version_identity()


def test_gui_build_rejects_another_checkout_with_the_same_version(build_identity, monkeypatch):
    release, initializer = build_identity
    other = initializer.parents[2] / "another-checkout" / "__init__.py"
    other.parent.mkdir()
    other.write_bytes(initializer.read_bytes())
    monkeypatch.setattr(release.djhx_bilix, "__file__", str(other))
    with pytest.raises(RuntimeError, match="from another checkout"):
        release.require_version_identity()


@pytest.mark.parametrize("content", [b"# version missing\n", b'__version__="1"\n__version__="2"'])
def test_gui_build_rejects_missing_or_repeated_source_version(build_identity, content):
    release, initializer = build_identity
    initializer.write_bytes(content)
    with pytest.raises(RuntimeError, match="exactly one source version"):
        release.require_version_identity()


@pytest.mark.parametrize(
    ("module_name", "entry"),
    [
        ("build_gui_windows", "require_build_environment"),
        ("package_gui_windows", "main"),
        ("build_gui_linux", "require_environment"),
        ("package_gui_deb", "require_environment"),
    ],
)
def test_all_gui_build_and_package_entries_reject_identity_before_work(
    monkeypatch, module_name, entry
):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    module = importlib.import_module(module_name)
    monkeypatch.setattr(module.sys, "argv", [module_name])

    def reject():
        raise RuntimeError("mixed release identity fixture")

    monkeypatch.setattr(module, "require_version_identity", reject)
    with pytest.raises(RuntimeError, match="mixed release identity fixture"):
        getattr(module, entry)()


@pytest.mark.parametrize("module_name", ["build_windows", "package_windows"])
@pytest.mark.parametrize("fault", ["metadata", "old-import-and-metadata", "other-source"])
def test_cli_entries_reject_identity_before_nuitka_or_zip(
    build_identity, monkeypatch, tmp_path, module_name, fault
):
    release, initializer = build_identity
    module = importlib.import_module(module_name)
    output = tmp_path / "must-not-write"
    arguments = (
        ["--output", str(output)]
        if module_name == "build_windows"
        else [str(tmp_path / "fixture.exe"), str(output / "fixture.zip")]
    )
    monkeypatch.setattr(module.sys, "argv", [module_name, *arguments])
    if fault == "metadata":
        monkeypatch.setattr(release.importlib.metadata, "version", lambda _name: "1.7.0")
        error = "metadata 1.7.0 differ"
    elif fault == "old-import-and-metadata":
        monkeypatch.setattr(release, "__version__", "1.7.0")
        error = "imported version 1.7.0"
    else:
        monkeypatch.setattr(release.djhx_bilix, "__file__", str(initializer.parent / "other.py"))
        error = "from another checkout"

    def forbidden(*_args, **_kwargs):
        pytest.fail("Identity mismatch reached compilation or packaging")

    if module_name == "build_windows":
        monkeypatch.setattr(module.subprocess, "run", forbidden)
    else:
        monkeypatch.setattr(module.tempfile, "TemporaryDirectory", forbidden)
        monkeypatch.setattr(module.zipfile, "ZipFile", forbidden)
    with pytest.raises(RuntimeError, match=error):
        module.main()
    assert not output.exists()
