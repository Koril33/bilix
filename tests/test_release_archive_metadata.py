"""The final assembler requires exact Python versions and bundled notices."""

import importlib
import tarfile
import zipfile
from io import BytesIO
from pathlib import Path

import pytest


def _assembler(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("assemble_release")


def _python_archive(assembler, tmp_path, kind, *, metadata_version=None, source_version=None):
    version = assembler.__version__
    metadata_version = version if metadata_version is None else metadata_version
    source_version = version if source_version is None else source_version
    metadata = f"Metadata-Version: 2.4\nName: djhx-bilix\nVersion: {metadata_version}\n\n".encode()
    initializer = (
        '"""Shared Bilibili downloader for the CLI and desktop GUI."""\n\n'
        f'__version__ = "{source_version}"\n'
    ).encode()
    if kind == "wheel":
        path = tmp_path / f"djhx_bilix-{version}-py3-none-any.whl"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(f"djhx_bilix-{version}.dist-info/METADATA", metadata)
            archive.writestr("djhx_bilix/__init__.py", initializer)
            archive.writestr("djhx_bilix/gui/app.py", b"# current GUI fixture\n")
    else:
        path = tmp_path / f"djhx_bilix-{version}.tar.gz"
        contents = {
            "PKG-INFO": metadata,
            "src/djhx_bilix/__init__.py": initializer,
            "src/djhx_bilix/gui/app.py": b"# current GUI fixture\n",
            "scripts/assemble_gui_release.py": b"# fixture\n",
            "LICENSE": b"license fixture\n",
        }
        with tarfile.open(path, "w:gz") as archive:
            for name, content in contents.items():
                member = tarfile.TarInfo(f"djhx_bilix-{version}/{name}")
                member.size = len(content)
                archive.addfile(member, BytesIO(content))
    return path


@pytest.mark.parametrize("kind", ["wheel", "sdist"])
def test_python_archive_accepts_consistent_source_and_metadata(monkeypatch, tmp_path, kind):
    assembler = _assembler(monkeypatch)
    path = _python_archive(assembler, tmp_path, kind)
    getattr(assembler, f"_verify_python_{kind}")(path)


@pytest.mark.parametrize("kind", ["wheel", "sdist"])
@pytest.mark.parametrize(
    ("metadata_version", "source_version", "error"),
    [
        ("1.7.0", None, "metadata.*wrong.*version"),
        (None, "1.7.0", "source version differs"),
        ("1.7.0", "1.7.0", "metadata.*wrong.*version"),
    ],
)
def test_python_archive_rejects_mixed_old_and_current_release_sources(
    monkeypatch, tmp_path, kind, metadata_version, source_version, error
):
    assembler = _assembler(monkeypatch)
    path = _python_archive(
        assembler,
        tmp_path,
        kind,
        metadata_version=metadata_version,
        source_version=source_version,
    )
    with pytest.raises(RuntimeError, match=error):
        getattr(assembler, f"_verify_python_{kind}")(path)


@pytest.mark.parametrize("kind", ["wheel", "sdist"])
def test_python_archive_rejects_renamed_old_filename(monkeypatch, tmp_path, kind):
    assembler = _assembler(monkeypatch)
    path = _python_archive(assembler, tmp_path, kind)
    wrong_name = path.with_name(path.name.replace(assembler.__version__, "1.7.0"))
    path.rename(wrong_name)
    with pytest.raises(RuntimeError, match="filename has the wrong version"):
        getattr(assembler, f"_verify_python_{kind}")(wrong_name)


def test_wheel_rejects_extra_metadata_from_another_release(monkeypatch, tmp_path):
    assembler = _assembler(monkeypatch)
    path = _python_archive(assembler, tmp_path, "wheel")
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr("djhx_bilix-1.7.0.dist-info/METADATA", b"Version: 1.7.0\n")
    with pytest.raises(RuntimeError, match="mixed or repeated"):
        assembler._verify_python_wheel(path)


def test_python_archive_rejects_repeated_version_header(monkeypatch, tmp_path):
    assembler = _assembler(monkeypatch)
    with pytest.raises(RuntimeError, match="repeated version"):
        assembler._verify_python_identity(
            f"Name: djhx-bilix\nVersion: {assembler.__version__}\nVersion: 1.7.0\n".encode(),
            f'__version__ = "{assembler.__version__}"\n'.encode(),
            "fixture",
        )


def test_sdist_rejects_another_release_source_root(monkeypatch, tmp_path):
    assembler = _assembler(monkeypatch)
    path = _python_archive(assembler, tmp_path, "sdist")
    members = {}
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            members[member.name] = archive.extractfile(member).read()
    members["djhx_bilix-1.7.0/src/djhx_bilix/__init__.py"] = b'__version__ = "1.7.0"\n'
    with tarfile.open(path, "w:gz") as archive:
        for name, content in members.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, BytesIO(content))
    with pytest.raises(RuntimeError, match="mixed source version roots"):
        assembler._verify_python_sdist(path)


def test_python_archive_source_is_read_without_execution(monkeypatch, tmp_path):
    assembler = _assembler(monkeypatch)
    marker = tmp_path / "must-not-be-written"
    source = (
        f'__version__ = "{assembler.__version__}"\n'
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n"
    )
    assembler._verify_python_identity(
        f"Name: djhx-bilix\nVersion: {assembler.__version__}\n".encode(),
        source.encode(),
        "fixture",
    )
    assert not marker.exists()


def test_wheel_version_must_match_exactly(monkeypatch, tmp_path):
    assembler = _assembler(monkeypatch)
    path = _python_archive(assembler, tmp_path, "wheel", metadata_version="1.6.0.dev0")
    with pytest.raises(RuntimeError, match="wrong.*version"):
        assembler._verify_python_wheel(path)


def test_cli_archive_requires_nuitka_runtime_notice(monkeypatch, tmp_path):
    assembler = _assembler(monkeypatch)
    path = tmp_path / "fixture.zip"
    required = {
        "bilix.exe",
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
        "README.windows.md",
        "LICENSES/Python-LICENSE.txt",
        "LICENSES/nuitka-runtime/LICENSE-RUNTIME.txt",
        "LICENSES/DISTRIBUTIONS.json",
        "vendor/ffmpeg/COPYING.GPLv3",
        "vendor/ffmpeg/ffmpeg-7.1.5.tar.xz",
        "scripts/build_ffmpeg.sh",
    }
    with zipfile.ZipFile(path, "w") as archive:
        for name in required:
            archive.writestr(name, b"fixture")
    with pytest.raises(RuntimeError, match="nuitka-runtime/NOTICE.txt"):
        assembler._verify_cli_zip(path)
