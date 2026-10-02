"""Build the src package with pinned Nuitka, then verify the executable can start.

Run with: uv run --group build python scripts/build_windows.py
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from djhx_bilix import __version__

ROOT = Path(__file__).resolve().parents[1]


def smoke(executable: Path, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    copied = directory / "BiliX 测试.exe"
    shutil.copy2(executable, copied)
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    # Exercise redirected output on an English Windows code page, without env UTF-8 mode.
    environment["PYTHONUTF8"] = "0"
    environment["PYTHONIOENCODING"] = "cp1252"
    environment["PATH"] = os.pathsep.join(
        (str(Path(os.environ["SystemRoot"]) / "System32"), os.environ["SystemRoot"])
    )
    environment["BILIX_CONFIG_DIR"] = str(directory / "profile")
    results = []
    for arguments, expected in [
        (["--help"], 0),
        (["-h"], 0),
        (["auth", "status", "-h"], 0),
        (["auth", "status", "--json"], 0),
        (["--version"], 0),
        (["doctor"], 0),
        (["download", "--codec", "invalid", "BV1j4411W7F7"], 2),
    ]:
        result = subprocess.run(
            [str(copied), *arguments],
            cwd=directory,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        results.append(
            {
                "arguments": arguments,
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        if result.returncode != expected:
            (directory / "smoke.json").write_text(
                json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            raise RuntimeError(f"Executable smoke test failed: {arguments}")
    (directory / "smoke.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main():
    parser = argparse.ArgumentParser(description="Build and smoke-test BiliX on Windows")
    parser.add_argument("--mode", choices=("onefile", "standalone"), default="onefile")
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "windows")
    arguments = parser.parse_args()
    if os.name != "nt":
        parser.error("This build script requires Windows")
    output = arguments.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["NUITKA_CACHE_DIR"] = str(ROOT / "build" / "nuitka-cache")
    command = [
        sys.executable,
        "-X",
        "utf8",
        "-m",
        "nuitka",
        f"--mode={arguments.mode}",
        "--msvc=latest",
        "--lto=no",
        "--assume-yes-for-downloads",
        "--include-windows-runtime-dlls=yes",
        "--include-package=djhx_bilix",
        "--python-flag=isolated",
        f"--include-data-files={ROOT / 'src/djhx_bilix/assets/ffmpeg.exe'}="
        "djhx_bilix/assets/ffmpeg.exe",
        f"--output-dir={output}",
        "--output-filename=bilix.exe",
        f"--file-version={__version__}",
        f"--product-version={__version__}",
        "--product-name=BiliX",
        "--file-description=Bilibili video downloader",
        f"--report={output / 'compilation-report.xml'}",
        str(ROOT / "src/djhx_bilix/__main__.py"),
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
        raise SystemExit(f"Build failed; see {output / 'build.log'}")
    executable = (
        output / "bilix.exe"
        if arguments.mode == "onefile"
        else output / "__main__.dist" / "bilix.exe"
    )
    if arguments.mode == "onefile":
        smoke(executable, output / "独立 发布")
    else:
        # A standalone directory must be moved as a whole, including its resources.
        copied = output / "独立 发布" / "standalone"
        shutil.copytree(executable.parent, copied, dirs_exist_ok=True)
        smoke(copied / executable.name, copied)
    print(f"Built and verified: {executable}")


if __name__ == "__main__":
    main()
