"""Build and start-check the PySide6 GUI standalone runtime on Linux amd64.

Run on Ubuntu 22.04 x64 in a locked CPython 3.14.8 environment.
"""

import importlib.metadata
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from gui_release import GUI_ENTRY, ROOT, STANDALONE_NAME, require_version_identity, sha256

BUILD = ROOT / "build" / "gui" / "linux"
NUITKA = "4.2.2"
PYSIDE = "6.11.2"


def require_environment() -> None:
    require_version_identity()
    if sys.platform != "linux" or platform.machine() != "x86_64":
        raise RuntimeError("The first Linux GUI package targets Ubuntu/Debian x86_64")
    release = platform.freedesktop_os_release()
    if release.get("ID") != "ubuntu" or release.get("VERSION_ID") != "22.04":
        raise RuntimeError("Build on Ubuntu 22.04 x64 for the supported glibc baseline")
    if sys.version_info[:3] != (3, 14, 8):
        raise RuntimeError("GUI release builds require CPython 3.14.8")
    for name, expected in (("Nuitka", NUITKA), ("PySide6-Essentials", PYSIDE)):
        actual = importlib.metadata.version(name)
        if actual != expected:
            raise RuntimeError(f"Expected {name} {expected}, found {actual}")
    if not GUI_ENTRY.is_file():
        raise RuntimeError("GUI module entry is missing")
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("Install the distribution ffmpeg package before building and testing")


def smoke(executable: Path) -> None:
    if not executable.is_file():
        raise RuntimeError(f"Nuitka did not create {executable}")
    check_root = BUILD / "中文 空格 验证"
    if check_root.exists():
        # The target is a fixed subdirectory of the repository's ignored build tree.
        resolved = check_root.resolve()
        if BUILD.resolve() not in resolved.parents:
            raise RuntimeError("Refusing to remove a smoke directory outside build/gui/linux")
        shutil.rmtree(resolved)
    shutil.copytree(executable.parent, check_root)
    env = os.environ.copy()
    for name in ("PYTHONPATH", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "BILIX_FFMPEG"):
        env.pop(name, None)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["BILIX_CONFIG_DIR"] = str(check_root / "isolated-profile")
    env["BILIX_DOWNLOAD_DIR"] = str(check_root / "downloads")
    result = subprocess.run(
        [str(check_root / executable.name), "--smoke-test"],
        cwd=check_root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    (BUILD / "smoke.txt").write_text(
        f"sha256={sha256(executable)}\nexit_code={result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}\n",
        encoding="utf-8",
    )
    if result.returncode:
        raise RuntimeError(f"Packaged GUI start check failed; see {BUILD / 'smoke.txt'}")


def bundle_input_contexts(executable: Path) -> None:
    """Include desktop input backends omitted by Nuitka's default families."""
    import PySide6

    qt_root = Path(PySide6.__file__).parent / "Qt"
    input_contexts = executable.parent / "PySide6" / "qt-plugins" / "platforminputcontexts"
    input_contexts.mkdir(parents=True, exist_ok=True)
    for name in ("libcomposeplatforminputcontextplugin.so", "libibusplatforminputcontextplugin.so"):
        shutil.copy2(qt_root / "plugins" / "platforminputcontexts" / name, input_contexts / name)
    shutil.copy2(qt_root / "lib" / "libQt6DBus.so.6", executable.parent / "libQt6DBus.so.6")


def main() -> None:
    require_environment()
    BUILD.mkdir(parents=True, exist_ok=True)
    (BUILD / "smoke.txt").unlink(missing_ok=True)
    env = os.environ.copy()
    env["NUITKA_CACHE_DIR"] = str(ROOT / "build" / "nuitka-cache")
    env["NUITKA_UPDATE_CHECK"] = "never"
    command = [
        sys.executable,
        "-X",
        "utf8",
        "-m",
        "nuitka",
        "--mode=standalone",
        "--enable-plugin=pyside6",
        "--include-qt-plugins=platforms",
        # Desktop app: embedded EGLFS, native GTK theme and print plugins pull
        # libraries absent from clean Ubuntu/Debian installations.
        "--noinclude-qt-plugins=egldeviceintegrations,platformthemes,printsupport",
        "--lto=no",
        "--include-package=djhx_bilix",
        f"--include-data-files={ROOT / 'src/djhx_bilix/assets' / 'bilix-*.png'}=djhx_bilix/assets/",
        "--python-flag=isolated",
        f"--output-dir={BUILD}",
        "--output-filename=bilix-gui",
        "--product-name=BiliX GUI",
        "--company-name=djhx",
        f"--report={BUILD / 'compilation-report.xml'}",
        str(GUI_ENTRY),
    ]
    with (BUILD / "build.log").open("wb") as stream:
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
        )
    if result.returncode:
        raise RuntimeError(f"Nuitka failed; see {BUILD / 'build.log'}")
    executable = BUILD / STANDALONE_NAME / "bilix-gui"
    # The Essentials wheel ships a PDF image plugin but not libQt6Pdf.so.6.
    # Keep the other image codecs for icons and QR while omitting this unused
    # plugin from the release tree before its smoke check and ELF scan.
    pdf_plugin = executable.parent / "PySide6" / "qt-plugins" / "imageformats" / "libqpdf.so"
    pdf_plugin.unlink(missing_ok=True)
    # Nuitka's default plugin families omit platforminputcontexts. Ship only
    # the native compose/IBus backends for desktop text entry; the virtual
    # keyboard plugin depends on Qt Quick, outside the Essentials runtime.
    bundle_input_contexts(executable)
    smoke(executable)
    print(f"Built and start-checked {executable}")


if __name__ == "__main__":
    main()
