"""The final assembler requires exact Python versions and bundled notices."""

import importlib
import zipfile
from pathlib import Path

import pytest


def _assembler(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("assemble_release")


def test_wheel_version_must_match_exactly(monkeypatch, tmp_path):
    assembler = _assembler(monkeypatch)
    path = tmp_path / "fixture.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            f"djhx_bilix-{assembler.__version__}.dist-info/METADATA", "Version: 1.6.0.dev0\n"
        )
        archive.writestr("djhx_bilix/gui/app.py", b"fixture")
    with pytest.raises(RuntimeError, match="wrong version"):
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
