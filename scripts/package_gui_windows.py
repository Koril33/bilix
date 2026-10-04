"""Package verified GUI binaries as a portable EXE and an Inno Setup installer.

Run after scripts/build_gui_windows.py, in the same locked build environment.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from gui_release import (
    ROOT,
    STANDALONE_NAME,
    artifact_manifest,
    collect_licenses,
    copy_sources,
    sha256,
    version_parts,
)

from djhx_bilix import __version__

BUILD = ROOT / "build" / "gui" / "windows"
DIST = ROOT / "dist" / "gui"


def sidecar_archive(source_root: Path, destination: Path) -> None:
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(source_root.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source_root).as_posix())


def find_iscc() -> Path:
    candidates = []
    if configured := os.environ.get("BILIX_ISCC"):
        candidates.append(Path(configured))
    if found := shutil.which("ISCC.exe"):
        candidates.append(Path(found))
    for program_files in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if program_files:
            candidates.append(Path(program_files) / "Inno Setup 7" / "ISCC.exe")
    candidates.append(ROOT / "build" / "tools" / "inno7" / "tools" / "ISCC.exe")
    for candidate in candidates:
        if candidate.is_file():
            version = subprocess.run(
                [str(candidate), "--version"], capture_output=True, text=True, timeout=10
            )
            if version.returncode != 0 or version.stdout.strip() != "7.1.0":
                raise RuntimeError(f"Expected Inno Setup 7.1.0, found {version.stdout.strip()}")
            return candidate
    raise RuntimeError(
        "Inno Setup 7.1.0 ISCC.exe was not found; install it before building the installer"
    )


def require_smoked(executable: Path, record: Path) -> None:
    if not executable.is_file() or not record.is_file():
        raise RuntimeError(f"Build and start-check {executable} before packaging")
    content = record.read_text(encoding="utf-8")
    if "exit_code=0\n" not in content or f"sha256={sha256(executable)}\n" not in content:
        raise RuntimeError(f"The build or start-check is stale: {record}")


def compile_installer(stage: Path, temporary: Path, *, preview: bool) -> Path:
    iscc = find_iscc()
    output = temporary / "inno-output"
    output.mkdir()
    numeric, _ = version_parts()
    script = ROOT / "scripts" / "installer" / "bilix-gui.iss"
    command = [
        str(iscc),
        f"/DAppVersion={__version__}",
        f"/DNumericVersion={numeric}",
        f"/DStageDir={stage}",
        f"/DOutputDir={output}",
        f"/DChannel={'preview' if preview else 'stable'}",
        str(script),
    ]
    log = temporary / "inno-build.log"
    with log.open("wb") as stream:
        result = subprocess.run(
            command,
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
        )
    if result.returncode:
        failure_log = BUILD / "inno-build.log"
        shutil.copy2(log, failure_log)
        raise RuntimeError(f"Inno Setup failed; see {failure_log}")
    installer = output / f"BiliX-GUI-Setup-{__version__}-windows-x64.exe"
    if not installer.is_file():
        raise RuntimeError("Inno Setup returned success but the installer is missing")
    return installer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portable-only", action="store_true", help="skip Inno Setup packaging")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Run Windows GUI packaging on Windows")
    if sys.version_info[:3] != (3, 14, 8):
        parser.error("Release packaging requires CPython 3.14.8")
    _, preview = version_parts()
    onefile = BUILD / "onefile" / "BiliX-GUI.exe"
    standalone = BUILD / "standalone" / STANDALONE_NAME
    require_smoked(onefile, BUILD / "onefile" / "smoke.txt")
    if not args.portable_only:
        require_smoked(standalone / "BiliX-GUI.exe", BUILD / "standalone" / "smoke.txt")
        find_iscc()
    DIST.mkdir(parents=True, exist_ok=True)
    artifacts = []
    with tempfile.TemporaryDirectory(prefix="gui-package-", dir=BUILD) as raw_temporary:
        temporary = Path(raw_temporary)
        materials = temporary / "materials"
        materials.mkdir()
        shutil.copy2(ROOT / "LICENSE", materials / "LICENSE")
        shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", materials / "THIRD_PARTY_NOTICES.md")
        collect_licenses(materials / "LICENSES", linux=False)
        copy_sources(materials / "SOURCES", linux=False)
        portable = DIST / f"BiliX-GUI-Portable-{__version__}-windows-x64.exe"
        shutil.copy2(onefile, portable)
        artifacts.append(portable)
        licenses = DIST / f"BiliX-GUI-licenses-and-source-{__version__}-windows-x64.zip"
        sidecar_archive(materials, licenses)
        artifacts.append(licenses)
        if not args.portable_only:
            stage = temporary / "installer-stage"
            shutil.copytree(materials, stage)
            shutil.copytree(standalone, stage / "runtime")
            installer = compile_installer(stage, temporary, preview=preview)
            target = DIST / installer.name
            shutil.copy2(installer, target)
            artifacts.append(target)
    artifact_manifest(
        artifacts,
        DIST / "release-manifest-windows.json",
        checksums_destination=DIST / "SHA256SUMS-windows.txt",
    )
    print("Prepared GUI artifacts:")
    for path in artifacts:
        print(path)


if __name__ == "__main__":
    main()
