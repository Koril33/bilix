"""Build and start-check both PySide6 GUI formats on Windows x64.

Run with: uv run --locked --extra gui --group build python scripts/build_gui_windows.py
"""

import argparse
import importlib.metadata
import os
import platform
import shutil
import struct
import subprocess
import sys
from pathlib import Path

from gui_release import (
    GUI_ENTRY,
    ROOT,
    STANDALONE_NAME,
    require_version_identity,
    sha256,
    version_parts,
)

EXPECTED_NUITKA = "4.2.2"
EXPECTED_PYSIDE = "6.11.2"
FFMPEG = ROOT / "src" / "djhx_bilix" / "assets" / "ffmpeg.exe"


def require_build_environment() -> None:
    require_version_identity()
    if os.name != "nt" or platform.machine().casefold() not in {"amd64", "x86_64"}:
        raise RuntimeError("This release builder requires Windows x64")
    if struct.calcsize("P") * 8 != 64:
        raise RuntimeError("Use 64-bit CPython")
    if sys.version_info[:3] != (3, 14, 8):
        raise RuntimeError("GUI release builds require CPython 3.14.8; run uv sync --python 3.14.8")
    for name, expected in (("Nuitka", EXPECTED_NUITKA), ("PySide6-Essentials", EXPECTED_PYSIDE)):
        actual = importlib.metadata.version(name)
        if actual != expected:
            raise RuntimeError(
                f"Expected {name} {expected}, found {actual}; use the locked GUI build group"
            )
    if not GUI_ENTRY.is_file() or not FFMPEG.is_file():
        raise RuntimeError("GUI entry point or bundled Windows FFmpeg is missing")


def executable_for(output: Path, mode: str) -> Path:
    if mode == "onefile":
        return output / "BiliX-GUI.exe"
    return output / STANDALONE_NAME / "BiliX-GUI.exe"


def smoke(executable: Path, output: Path, *, mode: str) -> None:
    """Run the packaged GUI from a Unicode directory with no developer Qt paths."""
    if not executable.is_file():
        raise RuntimeError(f"Nuitka did not create {executable}")
    smoke_root = output / "中文 空格 验证"
    smoke_root.mkdir(parents=True, exist_ok=True)
    if mode == "onefile":
        target = smoke_root / executable.name
        shutil.copy2(executable, target)
    else:
        target = executable
    env = os.environ.copy()
    for name in (
        "PYTHONPATH",
        "QT_PLUGIN_PATH",
        "QT_QPA_PLATFORM_PLUGIN_PATH",
        "BILIX_FFMPEG",
    ):
        env.pop(name, None)
    env["BILIX_CONFIG_DIR"] = str(smoke_root / "isolated-profile")
    env["BILIX_DOWNLOAD_DIR"] = str(smoke_root / "downloads")
    result = subprocess.run(
        [str(target), "--smoke-test"],
        cwd=smoke_root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    (output / "smoke.txt").write_text(
        f"mode={mode}\nsha256={sha256(executable)}\nexit_code={result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}\n",
        encoding="utf-8",
    )
    if result.returncode:
        raise RuntimeError(f"Packaged GUI start check failed; see {output / 'smoke.txt'}")


def build(mode: str, root_output: Path) -> Path:
    output = root_output / mode
    output.mkdir(parents=True, exist_ok=True)
    (output / "smoke.txt").unlink(missing_ok=True)
    environment = os.environ.copy()
    environment["NUITKA_CACHE_DIR"] = str(ROOT / "build" / "nuitka-cache")
    environment["NUITKA_UPDATE_CHECK"] = "never"
    file_version, _ = version_parts()
    command = [
        sys.executable,
        "-X",
        "utf8",
        "-m",
        "nuitka",
        f"--mode={mode}",
        "--enable-plugin=pyside6",
        "--windows-console-mode=disable",
        f"--windows-icon-from-ico={ROOT / 'src/djhx_bilix/assets/bilix.ico'}",
        "--msvc=latest",
        "--lto=no",
        "--assume-yes-for-downloads",
        "--include-windows-runtime-dlls=yes",
        "--include-package=djhx_bilix",
        "--python-flag=isolated",
        f"--include-data-files={FFMPEG}=djhx_bilix/assets/ffmpeg.exe",
        f"--include-data-files={ROOT / 'src/djhx_bilix/assets' / 'bilix-*.png'}=djhx_bilix/assets/",
        f"--include-data-files={ROOT / 'src/djhx_bilix/assets/action-*.svg'}=djhx_bilix/assets/",
        f"--output-dir={output}",
        "--output-filename=BiliX-GUI.exe",
        f"--file-version={file_version}",
        f"--product-version={file_version}",
        "--product-name=BiliX GUI",
        "--company-name=djhx",
        "--file-description=BiliX desktop downloader",
        f"--report={output / 'compilation-report.xml'}",
        str(GUI_ENTRY),
    ]
    with (output / "build.log").open("wb") as log:
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    if result.returncode:
        raise RuntimeError(f"Nuitka failed; see {output / 'build.log'}")
    executable = executable_for(output, mode)
    smoke(executable, output, mode=mode)
    return executable


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("both", "onefile", "standalone"), default="both")
    args = parser.parse_args()
    require_build_environment()
    root_output = ROOT / "build" / "gui" / "windows"
    modes = ("onefile", "standalone") if args.mode == "both" else (args.mode,)
    for mode in modes:
        print(f"Building GUI {mode}...", flush=True)
        executable = build(mode, root_output)
        print(f"Built and start-checked {executable}", flush=True)


if __name__ == "__main__":
    main()
